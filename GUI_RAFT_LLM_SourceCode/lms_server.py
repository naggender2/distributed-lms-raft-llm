import grpc
from concurrent import futures
import time
import json
import uuid
import lms_pb2
import lms_pb2_grpc
import os
import PyPDF2
from transformers import BertTokenizer, BertModel
import torch
import torch.nn.functional as F
import random
import argparse
import threading
from lms_pb2 import FileChunk, FileTransferResponse
from lms_pb2_grpc import FileTransferServiceStub
import shlex


def extract_text_from_pdf(file_path):
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
    return text

#Folder to store PDF
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Database file for persistence
DATABASE_FILE = 'lms_data.json'

# Initialize tutoring server connection
#EDIT THE IP ADDRESSES BELOW
tutoring_channel = grpc.insecure_channel('172.17.82.219:50054')
tutoring_stub = lms_pb2_grpc.TutoringStub(tutoring_channel)


# Load database from file
def load_data():
    try:
        with open(DATABASE_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {"users": {}, "assignments": {}, "grades": {}, "course_materials": []}
    

def save_data(new_data, merge=False):
    """
    Saves data to the JSON file.

    Args:
    - new_data (dict): The new data to save.
    - merge (bool): If True, merge with the existing data instead of overwriting.
    """
    try:
        # Load the existing data if merging
        if merge:
            try:
                with open(DATABASE_FILE, 'r') as file:
                    current_data = json.load(file)
            except FileNotFoundError:
                current_data = {}  # Initialize if the file does not exist

            # Merge the new data with the current data
            _deep_merge(current_data, new_data)
        else:
            current_data = new_data  # Overwrite if not merging

        # Save the merged or new data back to the JSON file
        with open(DATABASE_FILE, 'w') as file:
            json.dump(current_data, file, indent=4)

        print(f"Data successfully saved to {DATABASE_FILE}")

    except IOError as e:
        print(f"Failed to write to file: {e}")
        raise

def _deep_merge(dict1, dict2):
    """
    Recursively merges dict2 into dict1.
    """
    for key, value in dict2.items():
        if isinstance(value, dict) and key in dict1:
            _deep_merge(dict1[key], value)
        else:
            dict1[key] = value




def compute_embeddings(text, model, tokenizer):
    inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1)  # Use mean of token embeddings for simplicity

def cosine_similarity(emb1, emb2):
    return F.cosine_similarity(emb1, emb2).item()


# Global variables for Raft
myState = "Follower"
myTerm = 0
votedId = -1
myLeaderId = -1
commitIndex = 0
lastApplied = 0
logs = []
timer = 0
timerLimit = random.randint(500, 1000)  # Increased random election timeout
nextIndex = {}
matchIndex = {}



# RaftService class for handling Raft protocol
class RaftService(lms_pb2_grpc.RaftServiceServicer):
    def __init__(self,server_id):
        self.server_id = server_id
        self.term = 0
        self.voted_for = None
        self.log = []
        self.commitIndex = 0
        self.lastApplied = 0
        self.state = "Follower"
        self.leader_id = None
        self.timer = 0
        self.timerLimit = random.randint(1000, 2000)  # Increased random election timeout
        self.nextIndex = {}
        self.matchIndex = {}
        self.peers = {}  # Initialize peers as an empty dictionary

        # Initialize LMSService within RaftService
        self.lms_service = None  # LMSService reference will be injected later

    

    # RequestVote RPC implementation (handles election voting)
    def RequestVote(self, request, context):
     term = request.candidate.term
     candidate_id = request.candidate.candidateID
     last_log_index = request.lastLogIndex
     last_log_term = request.lastLogTerm
 
     # Step down if candidate's term is higher
     if term > self.term:
         self.step_down(term)
 
     # Reject vote if we already have a leader in the current term
     if self.leader_id is not None and term == self.term:
         print(f"Server {self.server_id}: Rejecting vote request from candidate {candidate_id} (already have a leader: {self.leader_id}).")
         return lms_pb2.RequestVoteResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=False))
 
     # Grant vote if we haven't voted this term and candidate's log is up-to-date
     if (self.voted_for is None or self.voted_for == candidate_id) and term >= self.term:
         if len(self.log) == 0:  # Empty log case
             self.voted_for = candidate_id
             print(f"Server {self.server_id}: Voted for candidate {candidate_id} in term {self.term} (Empty log case)")
             return lms_pb2.RequestVoteResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=True))
         elif last_log_term > self.log[-1]["term"] or (last_log_term == self.log[-1]["term"] and last_log_index >= len(self.log) - 1):
             self.voted_for = candidate_id
             print(f"Server {self.server_id}: Voted for candidate {candidate_id} in term {self.term}")
             return lms_pb2.RequestVoteResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=True))
         else:
             print(f"Server {self.server_id}: Vote denied for candidate {candidate_id} (Log not up-to-date)")
             return lms_pb2.RequestVoteResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=False))
 
     # Reject vote if already voted for someone else or candidate's term is lower
     if self.voted_for is not None and self.voted_for != candidate_id:
         print(f"Server {self.server_id}: Vote denied for candidate {candidate_id} (Already voted for {self.voted_for})")
     elif term < self.term:
         print(f"Server {self.server_id}: Vote denied for candidate {candidate_id} (Candidate's term is lower)")
 
     return lms_pb2.RequestVoteResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=False))
 
 

    # AppendEntries RPC implementation (heartbeat and log replication)
    def AppendEntries(self, request, context):
     """
     RAFT AppendEntries RPC, used for heartbeats or log replication.
     """
     # Step 1: Term check, reject if leader's term is stale
     if request.leader.term < self.term:
         print(f"Server {self.server_id}: Rejecting AppendEntries from leader {request.leader.leaderID} due to stale term.")
         return lms_pb2.AppendEntriesResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=False))
 
     # Step 2: Update term and leader information if leader's term is higher
     if request.leader.term > self.term:
         self.step_down(request.leader.term)

     if self.leader_id != request.leader.leaderID:
         # Mismatch detected, update to the correct leader
         print(f"Server {self.server_id}: Leader mismatch (expected {self.leader_id}, got {request.leader.leaderID}). Updating leader to {request.leader.leaderID}.")
         self.leader_id = request.leader.leaderID  # Reset leader to the correct one
 
     # Always accept the heartbeat if it is from the expected leader
     self.reset_timer()  # Reset election timeout on valid heartbeat
     print(f"Server {self.server_id} received heartbeat from Leader {self.leader_id} for term {self.term}")
 
     # If no log entries to append, this is just a heartbeat
     if not request.entries:
         print(f"Server {self.server_id}: Received heartbeat with no log entries.")
         return lms_pb2.AppendEntriesResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=True))
 
     # Step 4: Log Replication Logic
     prevLogIndex = request.prevLogIndex
     prevLogTerm = request.prevLogTerm
 
     # Check if the follower's log matches the leader's at prevLogIndex and prevLogTerm
     if prevLogIndex >= len(self.log) or (prevLogIndex >= 0 and self.log[prevLogIndex]["term"] != prevLogTerm):
         # Log mismatch: Truncate follower's log from prevLogIndex onwards
         print(f"Server {self.server_id}: Log mismatch detected. Truncating log from index {prevLogIndex + 1}.")
         self.log = self.log[:prevLogIndex + 1]  # Truncate the log starting at prevLogIndex
 
     # Step 4.1: Append new log entries if log matches after truncation
     new_entries = request.entries
     print(f"Server {self.server_id}: Appending {len(new_entries)} new entries to log after truncation")
 
     for i, entry in enumerate(new_entries):
         log_index = prevLogIndex + 1 + i
         entry_to_append = {"term": entry.term, "command": entry.command}  # Format the log entry
 
         if log_index < len(self.log):
             self.log[log_index] = entry_to_append  # Overwrite conflicting entry (unlikely after truncation)
             print(f"Server {self.server_id}: Overwriting log entry at index {log_index}.")
         else:
             self.log.append(entry_to_append)  # Append new entry
             print(f"Server {self.server_id}: Appended new log entry at index {log_index}.")
 
     # Step 5: Update commit index if leaderCommit is greater than current commit index
     if request.leaderCommit > self.commitIndex:
         old_commit_index = self.commitIndex
         self.commitIndex = min(request.leaderCommit, len(self.log) - 1)
         print(f"Server {self.server_id}: Updated commit index from {old_commit_index} to {self.commitIndex}.")
         
         # Apply any newly committed entries to the state machine after the majority agreement
         self._apply_commits(old_commit_index, self.commitIndex)
 
     # Return successful AppendEntries response
     print(f"Server {self.server_id}: Successfully appended entries and updated commit index.")
     return lms_pb2.AppendEntriesResponse(result=lms_pb2.TermResultPair(term=self.term, verdict=True))

 



    def _log_entry(self, entry):
        return {"term": entry.term, "command": entry.command}

    def _apply_commits(self, old_commit_index, new_commit_index):
        """
        Apply committed log entries to the LMS state machine via LMSService.
        This method is called when the commit index is updated.
        """
        for index in range(old_commit_index + 1, new_commit_index + 1):  # Apply entries between old and new commit index
            command = self.log[index]["command"].split(" ")  # Command is space-separated
            operation = command[0]

            if operation == "PostAssignment":
                # Use shlex to parse the command arguments correctly, treating quoted strings as single items
                parsed_command = shlex.split(" ".join(command[1:]))
                
                student = parsed_command[0]
                filename = parsed_command[1]
                file_path = parsed_command[2]
                assignment_text = parsed_command[3]  # This should now capture the full text, even with spaces
            
                self.lms_service._commit_post_assignment(student, filename, file_path, assignment_text)

            elif operation == "GradeAssignment":
                student_id = command[1]
                grade = command[2]
                self.lms_service._commit_grade_assignment(student_id, grade)

            elif operation == "PostCourseMaterial":
                instructor = command[1]
                filename = command[2]
                file_path = command[3]
                self.lms_service._commit_post_course_material(instructor, filename, file_path)

            elif operation == "AskQuery":
                username = command[1]
                query = " ".join(command[2:])  # Join the remaining parts as the query text
                self.lms_service._commit_ask_query(username, query)

            elif operation == "RespondToQuery":
                instructor = command[1]
                student_id = command[2]
                response = " ".join(command[3:])  # Join the remaining parts as the response
                self.lms_service._commit_respond_to_query(instructor, student_id, response)


            # NEW CASE: Handling user registration
            elif operation == "Register":
                username = command[1]
                password = command[2]
                role = command[3]
                self.lms_service._commit_register_user(username, password, role)


            print(f"Server {self.server_id}: applied command {command}")
            self.lastApplied += 1

        # Ensure changes are saved to the LMS data after applying each command
        save_data(self.lms_service.data, merge=True)

        


    def create_log_entry(self, operation, args):
     """
     Create a log entry with an operation name and its associated arguments.
     Ensure that multi-word strings are quoted to be treated as single arguments.
     """
     # Format arguments, wrapping multi-word strings in quotes
     formatted_args = [f'"{arg}"' if ' ' in arg else arg for arg in args]
     
     # Create the command string by joining the operation and formatted arguments
     command = f"{operation} {' '.join(formatted_args)}"
     log_entry = {"term": self.term, "command": command}
     
     # Append the log entry to the log
     self.log.append(log_entry)
     
     # Return the log entry
     return log_entry

    def create_log_entry(self, operation, args):
     # Serialize arguments using JSON to handle multi-word strings
     command = json.dumps({"operation": operation, "args": args})
     log_entry = {"term": self.term, "command": command}
     self.log.append(log_entry)
     return log_entry
    
    def ReplicateData(self, request, context):
        """
        Replicate assignment metadata to followers via Raft.
        """
        try:
            username = request.username
            assignment_metadata = request.assignment_metadata

            # Store metadata for replication
            if "assignments" not in self.data:
                self.data["assignments"] = {}

            if username not in self.data["assignments"]:
                self.data["assignments"][username] = []

            # Append metadata to follower's data store
            self.data["assignments"][username].append(assignment_metadata)

            # Persist data
            save_data(self.data, merge=True)

            # Return response indicating success
            return lms_pb2.ReplicateDataResponse(success=True)
    
        except Exception as e:
            print(f"Error replicating data: {str(e)}")
            # Return response indicating failure
            return lms_pb2.ReplicateDataResponse(success=False)
    

    

    # def replicate_log_entry(self, log_entry):
    #  # Iterate through peers and send AppendEntries RPC to each follower
    #  for peer_id, peer_address in self.peers.items():
    #      if peer_id != self.server_id:
    #          channel = grpc.insecure_channel(peer_address)
    #          stub = lms_pb2_grpc.RaftServiceStub(channel)
    #          try:
    #              # Build AppendEntriesRequest with log entry
    #              request = lms_pb2.AppendEntriesRequest(
    #                  leader=lms_pb2.TermLeaderIDPair(term=self.term, leaderID=self.server_id),
    #                  prevLogIndex=len(self.log) - 2,
    #                  prevLogTerm=self.log[-2]["term"] if len(self.log) > 1 else 0,
    #                  entries=[log_entry],
    #                  leaderCommit=self.commitIndex  # Send leader's commit index for followers to update
    #              )
    #              response = stub.AppendEntries(request)
    #              if response.result.verdict:
    #                  # Track how many followers accepted the entry
    #                  self.matchIndex[peer_id] = len(self.log) - 1  # Track replication progress
    #              else:
    #                 print(f"Server {peer_id} rejected log entry replication.")

    #              self.check_commit_index()  # Check if new entries can be committed       
    #          except grpc.RpcError as e:
    #              print(f"Failed to replicate log entry to Server {peer_id}: {e}")


 
 

            
    # def check_commit_index(self):
    #  """
    #  Checks if any new log entries can be committed based on replication status across the majority of servers.
    #  Ensures that the leader only commits logs replicated on the majority of followers.
    #  """
    #  majority_count = (len(self.peers) // 2) + 1
 
    #  # Start checking from the latest log index down to the current commitIndex
    #  for index in range(len(self.log) - 1, self.commitIndex, -1):
    #      # Count how many followers have replicated this log entry
    #      match_count = sum(1 for peer_id, match_idx in self.matchIndex.items() if match_idx >= index)
 
    #      # Log the replication status for debugging
    #      print(f"Server {self.server_id}: Checking log index {index}. Replicated on {match_count} followers (majority required: {majority_count}).")
 
    #      # Commit the log entry if it is replicated on the majority of servers and is from the current term
    #      if match_count >= majority_count and self.log[index]["term"] == self.term:
    #          old_commit_index = self.commitIndex
    #          self.commitIndex = index  # Update commit index
    #          print(f"Server {self.server_id}: Log entry at index {index} replicated on majority, committing it. CommitIndex updated from {old_commit_index} to {self.commitIndex}.")
 
    #          # Apply the newly committed log entries to the state machine
    #          self._apply_commits(old_commit_index,self.commitIndex)
    #          # Immediately propagate the new commitIndex to followers
    #          self.send_heartbeat()  # Force an immediate heartbeat with the updated commitIndex
    #          break
    #      else:
    #          # Log why the entry is not being committed
    #          if match_count < majority_count:
    #              print(f"Server {self.server_id}: Log entry at index {index} not committed. Only {match_count} replicas, but majority of {majority_count} required.")
    #          if self.log[index]["term"] != self.term:
    #              print(f"Server {self.server_id}: Log entry at index {index} not committed. Entry is from term {self.log[index]['term']}, but current term is {self.term}.")
 
    #  # Final log to indicate completion of commit checks
    #  print(f"Server {self.server_id}: Finished checking log entries for commitment.")


    def replicate_log_entry(self, log_entry):
     """
     Replicates a log entry to all followers.
     """
     for peer_id, peer_address in self.peers.items():
         if peer_id != self.server_id:
             channel = grpc.insecure_channel(peer_address)
             stub = lms_pb2_grpc.RaftServiceStub(channel)
             try:
                 # Build AppendEntriesRequest with the correct log range for each follower
                 request = lms_pb2.AppendEntriesRequest(
                     leader=lms_pb2.TermLeaderIDPair(term=self.term, leaderID=self.server_id),
                     prevLogIndex=self.nextIndex[peer_id] - 1,
                     prevLogTerm=self.log[self.nextIndex[peer_id] - 1]["term"] if self.nextIndex[peer_id] > 0 else 0,
                     entries=self.log[self.nextIndex[peer_id]:],  # Send entries starting from nextIndex
                     leaderCommit=self.commitIndex
                 )
                 response = stub.AppendEntries(request)
                 if response.result.verdict:
                     # Update matchIndex and nextIndex for successful replication
                     self.matchIndex[peer_id] = len(self.log) - 1
                     self.nextIndex[peer_id] = len(self.log) 
                     print(f"Server {peer_id}: Log replicated successfully. Updated matchIndex to {self.matchIndex[peer_id]} and nextIndex to {self.nextIndex[peer_id]}.")
                 else:
                     # Decrement nextIndex for retry if replication failed
                     self.nextIndex[peer_id] = max(1, self.nextIndex[peer_id] - 1)
                     print(f"Server {peer_id} rejected log entry. Decrementing nextIndex to {self.nextIndex[peer_id]}.")
                 # Check if the log can be committed
                 self.check_commit_index()
             except grpc.RpcError as e:
                 print(f"Failed to replicate log entry to Server {peer_id}: {e}")



    def check_commit_index(self):
     """
     Checks if any new log entries can be committed based on replication status across the majority of servers.
     Ensures that the leader only commits logs replicated on the majority of followers.
     """
     majority_count = (len(self.peers) // 2) + 1
 
     # Start checking from the latest log index down to the current commitIndex
     for index in range(len(self.log) - 1, self.commitIndex, -1):
         # Count how many followers have replicated this log entry
         match_count = sum(1 for peer_id, match_idx in self.matchIndex.items() if match_idx >= index)
 
         # Log the replication status for debugging
         print(f"Server {self.server_id}: Checking log index {index}. Replicated on {match_count} followers (majority required: {majority_count}).")
 
         # Commit the log entry if it is replicated on the majority of servers and is from the current term
         if match_count >= majority_count and self.log[index]["term"] == self.term:
             old_commit_index = self.commitIndex
             self.commitIndex = index  # Update commit index
             print(f"Server {self.server_id}: Log entry at index {index} replicated on majority, committing it. CommitIndex updated from {old_commit_index} to {self.commitIndex}.")
 
             # Apply the newly committed log entries to the state machine
             self._apply_commits(old_commit_index, self.commitIndex)
             # Immediately propagate the new commitIndex to followers
             self.send_heartbeat()  # Force an immediate heartbeat with the updated commitIndex
             break
         else:
             # Log why the entry is not being committed
             if match_count < majority_count:
                 print(f"Server {self.server_id}: Log entry at index {index} not committed. Only {match_count} replicas, but majority of {majority_count} required.")
             if self.log[index]["term"] != self.term:
                 print(f"Server {self.server_id}: Log entry at index {index} not committed. Entry is from term {self.log[index]['term']}, but current term is {self.term}.")
 
     # Final log to indicate completion of commit checks
     print(f"Server {self.server_id}: Finished checking log entries for commitment.")
 



 

 







    # Election logic
    def start_election(self):
     # Reset the election timer when starting an election
     self.reset_timer()
 
     # Increment term for new election
     self.term += 1
     self.voted_for = self.server_id  # Self vote
     vote_count = 1  # Self vote
     total_peers = len(self.peers)  # Total number of peers including self
     majority_threshold = (total_peers // 2) + 1  # Majority needed to win
 
     print(f"Server {self.server_id} starting election for term {self.term}")

     # Reset `voted_for` and `leader_id` before starting the new election
     self.voted_for = None
 
     # Abort if a leader is detected
     if self.leader_id is not None:
         print(f"Server {self.server_id}: Detected leader {self.leader_id}, aborting election")
         self.reset_timer()  # Reset timer if leader is found
         return
 
     # Now reset leader_id since an election is starting and no leader was found
     self.leader_id = None
 
     # Randomize election timeout to avoid split votes
     election_timeout = random.uniform(1.0, 2.0)
 
     for peer_id, peer_address in self.peers.items():
         if peer_id != self.server_id:
 
             # Stop if majority is already reached
             if vote_count >= majority_threshold:
                 break
 
             # Create gRPC channel to request votes from peers
             channel = grpc.insecure_channel(peer_address)
             stub = lms_pb2_grpc.RaftServiceStub(channel)
 
             last_log_index = len(self.log) - 1
             last_log_term = self.log[-1]["term"] if self.log else 0
 
             try:
                 print(f"Server {self.server_id} requesting vote from Server {peer_id}")
 
                 # Request vote from peer
                 response = stub.RequestVote(lms_pb2.RequestVoteRequest(
                     candidate=lms_pb2.TermCandIDPair(term=self.term, candidateID=self.server_id),
                     lastLogIndex=last_log_index, lastLogTerm=last_log_term))
 
                 # If the vote is granted, increment vote count
                 if response.result.verdict:
                     print(f"Server {self.server_id} received vote from Server {peer_id}")
                     vote_count += 1
                 else:
                     print(f"Server {self.server_id} did NOT receive vote from Server {peer_id}")
 
             except grpc.RpcError:
                 print(f"Server {self.server_id} failed to request vote from Server {peer_id}")
                 continue
 
     # Check if majority vote is reached
     if vote_count >= majority_threshold:
         self.state = "Leader"
         self.leader_id = self.server_id
         self.timer = 0  # Reset the election timer for heartbeats
         print(f"Server {self.server_id} elected as leader for term {self.term}")
         self.initialize_leader_state()
     else:
         self.state = "Follower"
         self.reset_timer()  # Reset the election timer after failed election
         print(f"Server {self.server_id} election failed, staying as follower")

 
 

    

    # Send heartbeats to followers (leader function)
    # Send heartbeats to followers (leader function)
    def send_heartbeat(self):
     print(f"Leader {self.server_id} (Term: {self.term}) sending heartbeats to peers...")
 
     for peer_id, peer_address in self.peers.items():
         if peer_id != self.server_id:
             channel = grpc.insecure_channel(peer_address)
             stub = lms_pb2_grpc.RaftServiceStub(channel)
 
             prev_log_index = len(self.log) - 1
             prev_log_term = self.log[prev_log_index]["term"] if prev_log_index >= 0 else 0
 
             try:
                 print(f"Leader {self.server_id} sending heartbeat to Server {peer_id} at {peer_address}")
 
                 # Build AppendEntriesRequest with empty entries for heartbeat
                 request = lms_pb2.AppendEntriesRequest(
                     leader=lms_pb2.TermLeaderIDPair(term=self.term, leaderID=self.server_id),
                     prevLogIndex=prev_log_index,
                     prevLogTerm=prev_log_term,
                     leaderCommit=self.commitIndex,
                     entries=[]
                 )
 
                 response = stub.AppendEntries(request, timeout=2)  # 2 seconds timeout
 
                 if response.result.verdict:
                     print(f"Heartbeat successful: Server {peer_id} responded with Success")
                 else:
                     print(f"Heartbeat failed: Server {peer_id} responded with Failure (Term: {response.term})")
 
                 # If the peer has a higher term, step down as leader
                 if response.result.term > self.term:
                     print(f"Server {peer_id} has a higher term ({response.term}). Stepping down as leader.")
                     self.step_down(response.result.term)
                     break
 
             except grpc.RpcError as e:
                 print(f"Failed to send heartbeat to Server {peer_id}: {e.code()} - {e.details()}")
                 # Continue even if failure occurs, unless majority is unreachable
                 continue
             finally:
                 # Always close the gRPC channel after the call
                 channel.close()
 
     print(f"Heartbeat round completed for Leader {self.server_id}.")


 


    def step_down(self, new_term):
     """
     Transition from Leader or Candidate to Follower and update the term.
     """
     print(f"Server {self.server_id} stepping down. New term: {new_term}")
     self.state = "Follower"  # Step down to Follower
     self.term = new_term     # Update to the new higher term
     self.voted_for = None    # Reset voted_for in the new term
     self.leader_id = None    # No leader known at this point
     self.timer = 0           # Reset election timer

    def reset_timer(self):
        """
        Resets the election timer to a random timeout value.
        """
        self.timer = 0
        self.timerLimit = random.randint(1000, 3000)
        print(f"Server {self.server_id}: Election timer reset to {self.timerLimit}ms")
    
    def initialize_leader_state(self):
        """
        Initialize leader state such as nextIndex and matchIndex for log replication.
        """
        print(f"Server {self.server_id}: Initializing leader state for term {self.term}")

        last_log_index = len(self.log)  # Index of the last log entry

        # Initialize nextIndex and matchIndex for each peer
        for peer_id in self.peers:
          if peer_id != self.server_id:
              self.nextIndex[peer_id] = last_log_index + 1  # Next entry to send
              self.matchIndex[peer_id] = 0  # Nothing has been replicated yet


    # (88)
    def WhoIsLeader(self, request, context):
     """Respond with the current leader ID."""
     if self.leader_id is not None:
         print(f"[Leader Info] Leader ID: {self.leader_id}")
         return lms_pb2.LeaderResponse(leader_id=self.leader_id)
     print(f"[Leader Info] No leader currently elected")
     return lms_pb2.LeaderResponse(leader_id=-1)  # No leader currently elected
 


    
 
    



# gRPC LMS Service
class LMSService(lms_pb2_grpc.LMSServicer):

    def __init__(self,server_id):
        self.data = load_data()
        self.server_id = server_id
        self.raft_service = None
        self.sessions = {}
        # # Load or initialize data
        # self.initialize_data(file_path)
        # file_path="lms_data.json"   insert this in init attributes


    # def initialize_data(self, file_path="lms_data.json"):
    #  """
    #  Load data from the JSON file or create default data if the file doesn't exist.
    #  """
    #  if os.path.exists(file_path):
    #      with open(file_path, 'r') as file:
    #          self.data = json.load(file)
    #          print(f"Data loaded from {file_path}.")
    #  else:
    #      # Initialize with default data structure if the file doesn't exist
    #      self.data = {
    #          "assignments": {},
    #          "users": {},
    #          "queries": {},
    #          "course_materials": {}
    #      }
    #      print(f"No data file found. Initialized default data structure.")
    #      save_data(self.data, file_path)


    def Register(self, request, context):
     username = request.username
     password = request.password
     role = request.role
 
     if username in self.data["users"]:
         return lms_pb2.RegisterResponse(success=False, message="Username already exists.")
     
     # Create the log entry for registering a new user
     log_entry = self.raft_service.create_log_entry("Register", [username, password, role])
 
     # Replicate the log entry to followers
     self.raft_service.replicate_log_entry(log_entry)
 
    #  # Wait until the entry is committed
    #  self.raft_service.check_commit_index()
 
    #  # Once committed, apply the operation locally
    #  self.data["users"][username] = {"password": password, "role": role}
    #  save_data(self.data)
     
     return lms_pb2.RegisterResponse(success=True, message="Registration request is being processed. Please wait.")


    def Login(self, request, context):
        username = request.username
        password = request.password
        if username in self.data["users"] and self.data["users"][username]["password"] == password:
            token = str(uuid.uuid4())
            self.sessions[token] = username
            return lms_pb2.LoginResponse(success=True, token=token, role=self.data["users"][username]["role"])
        return lms_pb2.LoginResponse(success=False)

    def Logout(self, request, context):
        token = request.token
        if token in self.sessions:
            del self.sessions[token]
            return lms_pb2.LogoutResponse(success=True)
        return lms_pb2.LogoutResponse(success=False)
    


    # def Post(self, request, context):
    #  token = request.token
    #  if token not in self.sessions:
    #      return lms_pb2.PostResponse(success=False)
 
    #  username = self.sessions[token]
    #  user_role = self.data["users"][username]["role"]
 
    #  # Instructors post course materials (PDFs)
    #  if user_role == "instructor" and request.type == "course_material":
         
    #      file_path = os.path.join(UPLOAD_FOLDER, request.filename)
    #      with open(file_path, 'wb') as f:
    #          f.write(request.file)  # Save the file to the server

    #       # Create the log entry for posting course material (only metadata, not the file itself)
    #      log_entry = self.raft_service.create_log_entry("PostCourseMaterial", [username, request.filename, file_path])
 
    #      # Replicate the log entry to followers
    #      self.raft_service.replicate_log_entry(log_entry)
 
    #      # Wait until the entry is committed
    #      self.raft_service.check_commit_index()
 
    #      # Once committed, apply the operation locally
    #     #  file_path = os.path.join(UPLOAD_FOLDER, request.filename)
    #     #  with open(file_path, 'wb') as f:
    #     #      f.write(request.file)  # Save the file to the server
 
    #      # Store the filename, path, and instructor's name
    #      self.data["course_materials"].append({
    #          "filename": request.filename,
    #          "filepath": file_path,
    #          "instructor": username  # Store the instructor's name
    #      })
    #      save_data(self.data)
    #      return lms_pb2.PostResponse(success=True)
 
    #  # Students post assignments (PDFs)
    #  elif user_role == "student" and request.type == "assignment":
         
    #      file_path = os.path.join(UPLOAD_FOLDER, request.filename)
    #      with open(file_path, 'wb') as f:
    #          f.write(request.file)


    #      # Create the log entry for posting an assignment
    #      # Create the log entry for posting an assignment (log only filename and file path, not file data)
    #      log_entry = self.raft_service.create_log_entry("UploadAssignment", [username, request.filename, file_path])
 
    #      # Replicate the log entry to followers
    #      self.raft_service.replicate_log_entry(log_entry)
 
    #      # Wait until the entry is committed
    #      self.raft_service.check_commit_index()
 
    #     #  # Once committed, apply the operation locally
    #     #  file_path = os.path.join(UPLOAD_FOLDER, request.filename)
    #     #  with open(file_path, 'wb') as f:
    #     #      f.write(request.file)
         
    #      # Extract and store text from the uploaded PDF
    #      assignment_text = extract_text_from_pdf(file_path)
    #      self.data["assignments"][username] = {
    #          "filename": request.filename,
    #          "filepath": file_path,
    #          "grade": None,
    #          "text": assignment_text  # Store extracted text
    #      }
    #      save_data(self.data)
    #      return lms_pb2.PostResponse(success=True)
 
    #  # Handle student query to instructor
    #  if user_role == "student" and request.type == "query":
    #      # Create the log entry for posting a query
    #      log_entry = self.raft_service.create_log_entry("AskQuery", [username, request.data])
 
    #      # Replicate the log entry to followers
    #      self.raft_service.replicate_log_entry(log_entry)
 
    #      # Wait until the entry is committed
    #      self.raft_service.check_commit_index()
 
    #      # Once committed, apply the operation locally
    #      # Store the query in the data structure for unanswered queries
    #      if "queries" not in self.data:
    #          self.data["queries"] = {}
 
    #      # Ensure each student's queries are stored under their username (or ID)
    #      if username not in self.data["queries"]:
    #          self.data["queries"][username] = []
 
    #      self.data["queries"][username].append({
    #          "query": request.data,
    #          "answered": False,
    #          "response": ""  # Changed 'instructor_response' to 'response' for consistency
    #      })
 
    #      save_data(self.data)
    #      return lms_pb2.PostResponse(success=True)
 
    #  return lms_pb2.PostResponse(success=False)


    def Post(self, request, context):
     token = request.token
     if token not in self.sessions:
         return lms_pb2.PostResponse(success=False)
 
     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]
 
     # Instructors post course materials (PDFs)
     if user_role == "instructor" and request.type == "course_material":
         
         file_path = os.path.join(UPLOAD_FOLDER, request.filename)
         with open(file_path, 'wb') as f:
             f.write(request.file)  # Save the file to the server
 
         # Create the log entry for posting course material (only metadata, not the file itself)
         log_entry = self.raft_service.create_log_entry("PostCourseMaterial", [username, request.filename, file_path])
 
         # Replicate the log entry to followers
         self.raft_service.replicate_log_entry(log_entry)
 
         # The actual state change should happen after the log is committed in _commit_post_course_material.
         return lms_pb2.PostResponse(success=True)
 
     # Students post assignments (PDFs)
     elif user_role == "student" and request.type == "assignment":
         
            file_path = os.path.join(UPLOAD_FOLDER, request.filename)
            with open(file_path, 'wb') as f:
                f.write(request.file)  # Save the file to the server
   
            # Extract text from the PDF for the assignment_text field
            assignment_text = extract_text_from_pdf(file_path)

            # Create the log entry for posting the assignment (includes metadata and text)
            log_entry = self.raft_service.create_log_entry("PostAssignment", [username, request.filename, file_path, assignment_text])

            # Replicate the log entry to followers
            self.raft_service.replicate_log_entry(log_entry)

            # The actual state change should happen after the log is committed in _commit_post_assignment.
            return lms_pb2.PostResponse(success=True)
 
     # Handle student query to instructor
     if user_role == "student" and request.type == "query":
         # Create the log entry for posting a query
         log_entry = self.raft_service.create_log_entry("AskQuery", [username, request.data])
 
         # Replicate the log entry to followers
         self.raft_service.replicate_log_entry(log_entry)
 
         # The actual state change should happen after the log is committed in _commit_ask_query.
         return lms_pb2.PostResponse(success=True)
 
     return lms_pb2.PostResponse(success=False)
 

    

    def GetUnansweredQueries(self, request, grpc_context):
     token = request.token
     if token not in self.sessions:
        return lms_pb2.GetResponse(success=False)

     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]

     if user_role != "instructor":
        return lms_pb2.GetResponse(success=False)

     result = []
    # Ensure 'queries' exists and iterate over student queries
     for student, queries in self.data.get("queries", {}).items():
        for query in queries:
            # Check if 'query' and 'response' exist and are unanswered
            if "query" in query and "response" in query and not query["answered"]:
                result.append(lms_pb2.DataEntry(id=student, data=query["query"]))

    # Return a valid response even if no queries are found
     return lms_pb2.GetResponse(success=True, entries=result if result else [])


    # def RespondToQuery(self, request, grpc_context):
    #  token = request.token
    #  if token not in self.sessions:
    #      return lms_pb2.PostResponse(success=False)
 
    #  username = self.sessions[token]
    #  user_role = self.data["users"][username]["role"]
 
    #  if user_role != "instructor":
    #      return lms_pb2.PostResponse(success=False)
 
    #  student_id = request.studentId  # Ensure this comes from the request
    #  response_text = request.data
 
    #  # Create the log entry for responding to a student's query
    #  log_entry = self.raft_service.create_log_entry("RespondToQuery", [username, student_id, response_text])
 
    #  # Replicate the log entry to followers
    #  self.raft_service.replicate_log_entry(log_entry)
 
    #  # Wait until the entry is committed
    #  self.raft_service.check_commit_index()
 
    #  # Once committed, apply the operation locally
    #  if student_id in self.data.get("queries", {}):
    #      for query in self.data["queries"][student_id]:
    #          if query["answered"] is False:  # Fix: Check for unanswered queries
    #              query["response"] = response_text  # Update with instructor's response
    #              query["answered"] = True  # Mark as answered
    #              save_data(self.data)  # Save updated data
    #              return lms_pb2.PostResponse(success=True)
 
    #  return lms_pb2.PostResponse(success=False)

    def RespondToQuery(self, request, grpc_context):
     token = request.token
     if token not in self.sessions:
         return lms_pb2.PostResponse(success=False)
 
     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]
 
     if user_role != "instructor":
         return lms_pb2.PostResponse(success=False)
 
     student_id = request.studentId  # Ensure this comes from the request
     response_text = request.data
 
     # Create the log entry for responding to a student's query
     log_entry = self.raft_service.create_log_entry("RespondToQuery", [username, student_id, response_text])
 
     # Replicate the log entry to followers
     self.raft_service.replicate_log_entry(log_entry)
 
     # Return a response indicating that the query response request is being processed
     return lms_pb2.PostResponse(success=True)






    def GetInstructorResponse(self, request, grpc_context):
     token = request.token
     if token not in self.sessions:
        return lms_pb2.GetResponse(success=False)

     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]

     if user_role != "student":
        return lms_pb2.GetResponse(success=False)

     result = []

    # Ensure 'queries' exists and check for instructor responses
     for student, queries in self.data.get("queries", {}).items():
        if student == username:
            for query in queries:
                if query.get("answered", False):
                    result.append(lms_pb2.DataEntry(
                        id=username,
                        data=f"Your Query: {query['query']}\nInstructor Response: {query['response']}"  # Fix: use 'response' instead of 'instructor_response'
                    ))

     return lms_pb2.GetResponse(success=True, entries=result)



    




# Modify the Get method to retrieve PDF files
    def Get(self, request, context):
     token = request.token
     if token not in self.sessions:
        return lms_pb2.GetResponse(success=False)

     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]
     result = []

    # Students get course materials (PDFs)
     if request.type == "course_material" and user_role == "student":
        # Check if course materials are available
       if not self.data["course_materials"]:
           return lms_pb2.GetResponse(success=True, message="No course materials available.")  # Changed to success=True

       # If materials exist, populate them
       for material in self.data["course_materials"]:
           with open(material["filepath"], 'rb') as f:
               file_content = f.read()
           result.append(lms_pb2.DataEntry(
               id="1",
               filename=material["filename"],
               file=file_content,
               instructor=material.get("instructor", "Unknown")  # Include the instructor name
           ))
       return lms_pb2.GetResponse(success=True, entries=result)
     
    #  # Instructors get student assignments (PDFs)
    #  if request.type == "assignment" and user_role == "instructor":
    # # Check if assignments exist
    #    if not self.data["assignments"]:
    #        return lms_pb2.GetResponse(success=True, message="No assignments available.")
       
    #    result = []  # Initialize the result list
   
    #    # Iterate over each student and their list of assignments
    #    for student, assignments in self.data["assignments"].items():
    #        # assignments is a list, so we need to iterate over each assignment for this student
    #        for assignment in assignments:
    #            # Open the assignment file
    #            with open(assignment["filepath"], 'rb') as f:
    #                file_content = f.read()
               
    #            # Append each assignment's details to the result
    #            result.append(lms_pb2.DataEntry(
    #                id=student,  # Student's ID for the assignment
    #                filename=assignment["filename"],
    #                file=file_content
    #            ))
       
    #    return lms_pb2.GetResponse(success=True, entries=result)



    # Instructors get student assignments (PDFs)
     # Instructors get student assignments (PDFs)
     if user_role == "instructor" and request.type == "student_list":
        for student, assignments in self.data["assignments"].items():
            for assignment in assignments:
                with open(assignment["filepath"], 'rb') as f:
                    file_content = f.read()  # This is the binary file content
                
                # Append each assignment's details to the result
                result.append(lms_pb2.DataEntry(
                    id=student,
                    filename=assignment["filename"],
                    file=file_content  # Ensure this is bytes
                ))
        return lms_pb2.GetResponse(success=True, entries=result)

     return lms_pb2.GetResponse(success=False, message="Invalid request type or unauthorized access")

    
# New GradeAssignment method
    # def GradeAssignment(self, request, context):
    #  token = request.token
    #  if token not in self.sessions:
    #      return lms_pb2.GradeResponse(success=False, message="Invalid session token")
 
    #  username = self.sessions[token]
    #  user_role = self.data["users"][username]["role"]
 
    #  if user_role != "instructor":
    #      return lms_pb2.GradeResponse(success=False, message="Only instructors can grade assignments")
 
    #  student = request.studentId
    #  grade = request.grade
 
    #  if student not in self.data["assignments"]:
    #      return lms_pb2.GradeResponse(success=False, message="Student assignment not found")
 
    #  # Create the log entry for grading the assignment
    #  log_entry = self.raft_service.create_log_entry("GradeAssignment", [username, student, grade])
 
    #  # Replicate the log entry to followers
    #  self.raft_service.replicate_log_entry(log_entry)
 
    #  # Wait until the entry is committed
    #  self.raft_service.check_commit_index()
 
    #  # Once committed, apply the operation locally
    #  # Store the grade separately in the grades dictionary
    #  self.data["grades"][student] = {"grade": grade}
 
    #  # Remove the student's assignment from the list after grading
    #  del self.data["assignments"][student]
    #  save_data(self.data)
 
    #  return lms_pb2.GradeResponse(success=True, message="Assignment graded and removed successfully")

    def GradeAssignment(self, request, context):
     token = request.token
     if token not in self.sessions:
         return lms_pb2.GradeResponse(success=False, message="Invalid session token")
 
     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]
 
     if user_role != "instructor":
         return lms_pb2.GradeResponse(success=False, message="Only instructors can grade assignments")
 
     student = request.studentId
     grade = request.grade
 
     if student not in self.data["assignments"]:
         return lms_pb2.GradeResponse(success=False, message="Student assignment not found")
 
     # Create the log entry for grading the assignment
     log_entry = self.raft_service.create_log_entry("GradeAssignment", [student, grade])
 
     # Replicate the log entry to followers
     self.raft_service.replicate_log_entry(log_entry)
 
     # Return a response indicating that the grading request is being processed
     return lms_pb2.GradeResponse(success=True, message="Grading request is being processed. Please wait.")



    

    def GetGrade(self, request, context):
     token = request.token
     if token not in self.sessions:
         return lms_pb2.GetGradeResponse(success=False, grade="Invalid session")
 
     username = self.sessions[token]
     user_role = self.data["users"][username]["role"]
 
     if user_role != "student":
         return lms_pb2.GetGradeResponse(success=False, grade="Only students can view grades")
 
     # Check if the student has any assignments in the "assignments" section
     if username in self.data["assignments"]:
         # Assuming each student has a list of assignment dictionaries
         assignments = self.data["assignments"][username]
 
         # Loop through assignments and return the grade of the first one found
         for assignment in assignments:
             if "grade" in assignment:
                 grade = assignment["grade"]
 
                 if grade is None:
                     return lms_pb2.GetGradeResponse(success=True, grade="Grade not yet assigned")
                 else:
                     return lms_pb2.GetGradeResponse(success=True, grade=f"Your grade: {grade}")
 
         # If no grade is found
         return lms_pb2.GetGradeResponse(success=True, grade="No grade assigned yet.")
 
     return lms_pb2.GetGradeResponse(success=True, grade="No assignments found for this student.")
 
    
    #LLM Query
    # LLM Query with Similarity Check
    def GetLLMAnswer(self, request, context):
        token = request.token
        if token not in self.sessions:
            return lms_pb2.QueryResponse(success=True, response="Invalid session.")
        
        username = self.sessions[token]
        user_role = self.data["users"][username]["role"]

        # Ensure the user is a student
        if user_role != "student":
            return lms_pb2.QueryResponse(success=True, response="Only students can ask queries.")

        query = request.query
        if username not in self.data["assignments"]:
            return lms_pb2.QueryResponse(success=True, response="No assignment found for this student.")

        # Get the student's assignment text
        assignment_text = self.data["assignments"][username][0]["text"]  # Access the first assignment's text


        # Compute embeddings for both the query and the assignment text
        model_name = "bert-base-uncased"
        model = BertModel.from_pretrained(model_name)
        tokenizer = BertTokenizer.from_pretrained(model_name)

        query_embedding = compute_embeddings(query, model, tokenizer)
        assignment_embedding = compute_embeddings(assignment_text, model, tokenizer)

        # Check similarity between query and assignment
        similarity = cosine_similarity(query_embedding, assignment_embedding)
        similarity_threshold = 0.6  # Adjust threshold as needed

        if similarity < similarity_threshold:
            return lms_pb2.QueryResponse(success=True, response="Your query does not relate to your assignment. Please ask a question related to your assignment.")
        
        # Forward the query to the LLM server if similarity check passes
        response = tutoring_stub.GetLLMAnswer(lms_pb2.QueryRequest(token=token, query=query))
        return response
    

    def _commit_register_user(self, username, password, role):
     """
     Commit the Register command to the state machine and save to file.
     """
     if "users" not in self.data:
         self.data["users"] = {}
 
     if username not in self.data["users"]:
         self.data["users"][username] = {
             "password": password,
             "role": role
         }
         print(f"User {username} registered with role {role}.")
     else:
         print(f"User {username} already exists!")
 
     # Persist the changes to the JSON file
     save_data(self.data, merge=True)
 

    

    def _commit_post_assignment(self, student, filename, file_path, assignment_text):
     """
     Commit the PostAssignment command to the state machine and save both the file and metadata.
     If this server is the leader, replicate the file to followers.
     """
     
     # Path to save the file
     file_save_path = os.path.join(UPLOAD_FOLDER, filename)
 
     # Ensure 'assignments' category exists in the data
     if "assignments" not in self.data:
         self.data["assignments"] = {}
 
     # Ensure the student's assignment list exists
     if student not in self.data["assignments"]:
         self.data["assignments"][student] = []
 
     # Create the assignment metadata dictionary
     assignment_metadata = {
         "filename": filename,
         "filepath": file_save_path,  # Store the file path metadata
         "grade": None,
         "text": assignment_text  # Store the extracted text from the PDF
     }
 
     # Append the new assignment to the student's list of assignments
     self.data["assignments"][student].append(assignment_metadata)
 
     # If the server is the leader, replicate the file to followers
     if self.raft_service.state == "Leader":
         try:
             # Distribute the file to followers out-of-band (manual file replication)
             self._replicate_file_to_followers(file_path, file_save_path)
         except Exception as e:
             print(f"Error replicating file to followers: {str(e)}")
             raise
 
     # Persist the metadata to the JSON file
     save_data(self.data, merge=True)
 
     print(f"Server {self.server_id}: Posted assignment {filename} by {student}")
 
 


    def _commit_grade_assignment(self, student_id, grade):
     """
     Commit the GradeAssignment command and save the grade for the student.
     """
     try:
         # Check if the student's assignment exists
         if student_id in self.data["assignments"]:
             # Loop through the assignments to update the grade
             for assignment in self.data["assignments"][student_id]:
                 assignment["grade"] = grade  # Assign the grade here
 
             print(f"Server {self.server_id}: Graded assignment for {student_id} - Grade: {grade}")
 
             # Persist the updated data (save changes)
             save_data(self.data, merge=True)
 
         else:
             print(f"Server {self.server_id}: Assignment for {student_id} not found!")
 
     except Exception as e:
         print(f"Error in _commit_grade_assignment: {str(e)}")
 
  

 

    def _commit_post_course_material(self, instructor, filename, file_path):
     """
     Commit the PostCourseMaterial command to the state machine and save both the file and metadata.
     If this server is the leader, replicate the file to followers.
     """
 
     # Path to save the file
     file_save_path = os.path.join(UPLOAD_FOLDER, filename)
 
     # Store metadata only, not the file content initially
     if "course_materials" not in self.data:
         self.data["course_materials"] = []
 
     # Append the course material metadata to the data
     self.data["course_materials"].append({
         "filename": filename,
         "filepath": file_save_path,  # Store path metadata, not the actual file
         "instructor": instructor
     })
 
     # If the server is the leader, replicate the file to followers
     if self.raft_service.state == "Leader":
         try:
             # Distribute the file to followers out-of-band (manual file replication)
             self._replicate_file_to_followers(file_path, file_save_path)
         except Exception as e:
             print(f"Error replicating file to followers: {str(e)}")
             raise
 
     # Persist the metadata to the JSON file
     save_data(self.data, merge=True)
 
     print(f"Server {self.server_id}: Posted course material {filename} by {instructor}")
 
 

    def _commit_ask_query(self, username, query):
     """
     Commit the AskQuery command to the state machine and save to file.
     """
     # Check if "queries" exists in the data, initialize if not
     if "queries" not in self.data:
         self.data["queries"] = {}
     
     # Check if the user has existing queries, initialize if not
     if username not in self.data["queries"]:
         self.data["queries"][username] = []
 
     # Append the new query
     self.data["queries"][username].append({
         "query": query,
         "answered": False,
         "response": None
     })
 
     print(f"Server {self.server_id}: {username} asked a query: {query}")
     
     # Persist only the query-related data
     save_data(self.data, merge=True)


    def _commit_respond_to_query(self, instructor, student_id, response):
     """
     Commit the RespondToQuery command to the state machine and save to file.
     """
     if "queries" in self.data and student_id in self.data["queries"]:
         for query in self.data["queries"][student_id]:
             if not query["answered"]:
                 # Update the query with the response
                 query["response"] = response
                 query["answered"] = True
                 print(f"Server {self.server_id}: {instructor} responded to {student_id}'s query with: {response}")
                 
                 # Persist only the updated queries section
                 save_data(self.data, merge=True)
                 return
         print(f"Server {self.server_id}: All queries for {student_id} have already been answered.")
     else:
         print(f"Server {self.server_id}: No queries found for {student_id}.")




    # Define a dictionary mapping server IDs to their IP addresses and ports
    SERVER_ADDRESSES = {
        1: "172.18.18.37:50051",
        2: "172.18.18.28:50052",
        3: "172.18.18.43:50053",
        4: "172.18.18.30:50054",
        5: "172.18.18.48:50055"
    }

    def _replicate_file_to_followers(self, source_path, destination_path):
        """
        Replicate the file content to followers via gRPC streaming.
        This method will send the file as chunks to each follower server.
        """
        CHUNK_SIZE = 1024 * 1024  # 1 MB chunk size
    
        for follower_id, address in self.SERVER_ADDRESSES.items():
            if follower_id != self.server_id:  # Skip self (leader) in replication
                try:
                    # Establish gRPC connection to follower
                    with grpc.insecure_channel(address) as channel:
                        stub = lms_pb2_grpc.FileTransferServiceStub(channel)
    
                        # Open the file and send it chunk by chunk
                        def file_chunk_generator():
                            with open(source_path, 'rb') as f:
                                while chunk := f.read(CHUNK_SIZE):
                                    yield lms_pb2.FileChunk(content=chunk, destination_path=destination_path)
    
                        # Call the SendFile method and pass the chunks
                        response = stub.SendFile(file_chunk_generator())
    
                        if response.success:  # Check the success field
                         print(f"File {source_path} replicated successfully to follower {follower_id} at {address}")
                        else:
                         print(f"Error replicating file to follower {follower_id} at {address}: Replication failed.")
    
    
                except Exception as e:
                    print(f"Failed to replicate file to follower {follower_id} at {address}: {str(e)}")



class FileTransferServicer(lms_pb2_grpc.FileTransferServiceServicer):
    def __init__(self):
        pass

    def SendFile(self, request_iterator, context):
     try:
         file_path = None
 
         for file_chunk in request_iterator:
             # Set the file path only once, using the destination_path from the first chunk
             if not file_path:
                 file_path = file_chunk.destination_path
 
             # Ensure the directory for the file exists
             os.makedirs(os.path.dirname(file_path), exist_ok=True)
 
             # Open the file in append-binary mode and write the chunk's content
             with open(file_path, 'ab') as f:
                 f.write(file_chunk.content)
 
         # After receiving all chunks, return a successful response
         return FileTransferResponse(status="File received successfully")
 
     except Exception as e:
         # Handle any errors during the file transfer
         return FileTransferResponse(status=f"Error receiving file: {str(e)}")
     


 
# gRPC Server
# Increase the max message size to 10 MB or a larger value
MAX_MESSAGE_LENGTH = 50 * 1024 * 1024  # 10 MB

# Function to handle Raft logic (runs in the background)
def raft_background_task(raft_service):
    while True:
        time.sleep(0.01)  # Heartbeat interval (10ms)

        # Increment the election timer for the follower or candidate
        raft_service.timer += 1

        # Follower times out and starts an election
        if raft_service.state == "Follower" and raft_service.timer >= raft_service.timerLimit:
            print(f"Server {raft_service.server_id}: Election timeout. Starting election for term {raft_service.term + 1}")

            # Reset leader since no heartbeats were received
            if raft_service.leader_id is not None:
                print(f"Server {raft_service.server_id}: No heartbeat from Leader {raft_service.leader_id}, resetting leader.")
                raft_service.leader_id = None  # Reset the leader ID since it's unresponsive

            raft_service.start_election()

        # Leader sends heartbeats periodically
        elif raft_service.state == "Leader":
            raft_service.send_heartbeat()

        # Candidate times out and restarts election (if no majority is reached within election timeout)
        elif raft_service.state == "Candidate" and raft_service.timer >= raft_service.timerLimit:
            print(f"Server {raft_service.server_id}: Candidate timeout. Restarting election for term {raft_service.term + 1}.")
            raft_service.start_election()  # Candidate times out and starts a new election if no majority is reached



# The serve function to run the gRPC server and Raft logic
def serve(server_id, port, peers):
    # Initialize LMSService and RaftService independently
    lms_service = LMSService(server_id)
    raft_service = RaftService(server_id)


    # Inject references to avoid circular dependency during initialization
    lms_service.raft_service = raft_service
    raft_service.lms_service = lms_service
    raft_service.peers = peers
    

    # Create the gRPC server
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ('grpc.max_send_message_length', 50 * 1024 * 1024),  # 50 MB send limit
            ('grpc.max_receive_message_length', 50 * 1024 * 1024)  # 50 MB receive limit
        ]
    )

    lms_pb2_grpc.add_LMSServicer_to_server(lms_service, server)
    lms_pb2_grpc.add_RaftServiceServicer_to_server(raft_service, server)
    lms_pb2_grpc.add_FileTransferServiceServicer_to_server(FileTransferServicer(), server)



    

    server.add_insecure_port(f"[::]:{port}")
    print(f"Server {server_id} starting on port {port}")


    # Start the Raft election and heartbeat logic in a separate thread
    threading.Thread(target=raft_background_task, args=(raft_service,), daemon=True).start()

    # Start the gRPC server
    server.start()
    print(f"Server {server_id} started on port {port}")
    # Wait for termination (blocks until server is stopped)
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("id", type=int)
    parser.add_argument("port", type=int)
    parser.add_argument("peers", nargs="+")
    args = parser.parse_args()

     # Assign peer IDs starting from 1 instead of 0
    peers = {i + 1: peer for i, peer in enumerate(args.peers)}  # Add +1 here
    serve(args.id, args.port, peers)