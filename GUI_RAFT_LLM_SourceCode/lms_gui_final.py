import tkinter as tk
from tkinter import messagebox
import grpc
import lms_pb2
import lms_pb2_grpc
import os
from tkinter.filedialog import asksaveasfilename
from concurrent.futures import ThreadPoolExecutor  # For non-blocking GUI operations
import time




class LMSApp:

    def __init__(self, root):
     self.root = root
     self.root.title("LMS System")
     


     #EDIT THE IP ADDRESSES BELOW
     self.server_addresses = [
         '172.18.18.37:50051',  # Address of Server 1
         '172.18.18.28:50052',  # Address of Server 2 
         '172.18.18.43:50053',  # Address of Server 3
         '172.18.18.30:50054',  # Address of Server 4
         '172.18.18.48:50055',  # Address of Server 5
     ]
 
     # Thread pool for async gRPC requests
     self.executor = ThreadPoolExecutor(max_workers=10)
     
     # Increase the max message size to 50MB
     MAX_MESSAGE_LENGTH = 50 * 1024 * 1024
 
     # Initialize leader address and gRPC channel dynamically (No hardcoded address)
     self.leader_address = None  # We will get the leader dynamically
     self.token = None
     self.role = None
 
     # Get the leader at the start
     try:
         self.leader_address = self.get_leader()
         self.channel = grpc.insecure_channel(
             self.leader_address,
             options=[
                 ('grpc.max_send_message_length', MAX_MESSAGE_LENGTH),
                 ('grpc.max_receive_message_length', MAX_MESSAGE_LENGTH),
             ]
         )
         self.stub = lms_pb2_grpc.LMSStub(self.channel)  # Initialize the stub with the leader
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to find a leader: {str(e)}")
 
     # Show login screen
     self.show_login()


    


    def get_leader(self):
     retry_attempts = 5  # Number of retries
     retry_delay = 3  # Seconds between retries
 
     # Iterate for a specified number of retry attempts
     for attempt in range(retry_attempts):
         for server in self.server_addresses:
             try:
                 print(f"Attempting to connect to server: {server}")
                 channel = grpc.insecure_channel(server)
                 stub = lms_pb2_grpc.RaftServiceStub(channel)
 
                 # Send a WhoIsLeader request to the current server
                 response = stub.WhoIsLeader(lms_pb2.Empty())

                 # Validate leader_id is within the range of server addresses
                 if 1 <= response.leader_id <= len(self.server_addresses):
 
                   # If the current server is the leader, return this server
                   if response.leader_id == self.server_addresses.index(server) + 1:
                       print(f"Leader found: Server {response.leader_id} is the leader.")
                       return server  # Return the leader's address
   
                   # If the server knows who the leader is, connect to that leader instead
                   elif response.leader_id != -1:
                       leader_address = self.server_addresses[response.leader_id - 1]
                       print(f"Redirecting to actual leader: Server {response.leader_id} at {leader_address}")
                       return leader_address
                   
                 else:
                     # Log invalid leader_id response and continue trying other servers
                     print(f"Invalid leader_id received: {response.leader_id}")
                     continue
 
             except grpc.RpcError as e:
                 print(f"Failed to communicate with server {server}: {e}")
                 continue  # Skip to the next server if this one fails

 
         # If no leader found, wait for the next retry attempt
         print(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds...")
         time.sleep(retry_delay)
 
     # If no leader found after all retry attempts
     raise Exception("No leader found after multiple retries. Please ensure at least two servers are running.")



    def communicate_with_leader_async(self, action, *args):
     """Asynchronously communicate with the leader server."""
     retry_count = 0
     max_retries = 3
 
     # Detect the leader first
    #  if self.leader_address is None:
    #      self.leader_address = self.get_leader()

     self.leader_address = self.get_leader()  # Always fetch the current leader


     if self.leader_address is None:
            print("No leader found after checking all servers.")
            raise Exception("Failed to find leader after checking all servers.")
 
     while retry_count < max_retries:
         try:
             # Create a channel to the current leader
             channel = grpc.insecure_channel(self.leader_address)
             stub = lms_pb2_grpc.LMSStub(channel)
 
             # Perform the action asynchronously using a thread pool
             future = self.executor.submit(action, stub, *args)
             return future
 
         except grpc.RpcError as e:
             # If there is a communication error, retry with a new leader
             if e.code() in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.UNKNOWN,
            grpc.StatusCode.DEADLINE_EXCEEDED,
            grpc.StatusCode.CANCELLED,
            grpc.StatusCode.RESOURCE_EXHAUSTED  # Optional, in case of server overload
        ):
                 print(f"Leader at {self.leader_address} is unavailable. Retrying with a new leader...")
                 self.leader_address = self.get_leader()  # Find the new leader
                 retry_count += 1
                 continue  # Retry with the new leader
             else:
                 # Re-raise other gRPC errors
                 raise e
 
     raise Exception("Unable to communicate with leader after multiple attempts.")
    

    # to check leader before any operation
    # def execute_with_leader(self, action, *args):
    #  """Ensures the leader is detected before executing the action."""
    #  try:
    #      # Detect the current leader
    #      self.leader_address = self.get_leader()  # Update the leader's address
    #      self.channel = grpc.insecure_channel(self.leader_address)  # Reinitialize the gRPC channel with the leader
    #      self.stub = lms_pb2_grpc.LMSStub(self.channel)  # Update the stub for the leader
 
    #      # Execute the action (e.g., login or register)
    #      action(*args)
    #  except Exception as e:
    #      messagebox.showerror("Error", f"Failed to communicate with leader: {str(e)}")

    def execute_with_leader(self, action, *args):
     """Ensures the leader is detected before executing the action."""
     try:
         # Detect the current leader
         self.leader_address = self.get_leader()  # Update the leader's address
         self.channel = grpc.insecure_channel(self.leader_address)  # Reinitialize the gRPC channel with the leader
         self.stub = lms_pb2_grpc.LMSStub(self.channel)  # Create a new LMSStub using the leader channel
 
         # Now execute the action by passing the stub and any additional arguments
         return action(self.stub, *args)  # action expects the stub and other arguments to be passed
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to communicate with leader: {str(e)}")
         raise e  # Re-raise the exception for proper handling

 
 
 






    def show_login(self):
     """Login window for students and instructors"""
     self.clear_window()
 
     # Set a bright background color for the overall window
     self.root.configure(bg="#FFFAF0")  # Light floral background
 
     # Configure title label with a modern style
     self.title_label = tk.Label(self.root, text="Login to LMS", font=("Helvetica", 24, "bold"), bg="#FFFAF0", fg="#007ACC")
     self.title_label.grid(row=0, column=0, columnspan=2, pady=(20, 30), padx=20)
 
     # Create a frame for better structure
     frame = tk.Frame(self.root, bg="#E2F0FE", bd=5, relief="groove")  # Light blue frame
     frame.grid(row=1, column=0, columnspan=2, padx=20, pady=20)
 
     # Configure username label and entry
     tk.Label(frame, text="Username:", font=("Helvetica", 14), bg="#E2F0FE", fg="#333").grid(row=0, column=0, pady=10, padx=20, sticky="e")
     self.username = tk.Entry(frame, font=("Helvetica", 14), bg="#FFFFFF", bd=2, relief="solid")
     self.username.grid(row=0, column=1, pady=10, padx=20)
 
     # Configure password label and entry
     tk.Label(frame, text="Password:", font=("Helvetica", 14), bg="#E2F0FE", fg="#333").grid(row=1, column=0, pady=10, padx=20, sticky="e")
     self.password = tk.Entry(frame, show="*", font=("Helvetica", 14), bg="#FFFFFF", bd=2, relief="solid")
     self.password.grid(row=1, column=1, pady=10, padx=20)
 
     # Add login button with bright styles
     login_button = tk.Button(frame, text="Login", font=("Helvetica", 14, "bold"), bg="#4CAF50", fg="white",
                              command=lambda: self.execute_with_leader(self.login), width=12, relief="raised")
     login_button.grid(row=2, column=1, pady=20, padx=20, sticky="e")
 
     # Add register button with bright styles
     register_button = tk.Button(frame, text="Register", font=("Helvetica", 14, "bold"), bg="#FF9800", fg="white",
                                 command=self.show_register, width=12, relief="raised")
     register_button.grid(row=2, column=0, pady=20, padx=20, sticky="w")
 
     # Center all the elements in the window
     self.root.grid_rowconfigure(0, weight=1)
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(1, weight=1)
 
     # Start the title animation
     self.animate_title()
 
    def animate_title(self):
     """Animate the title text color for visual effect."""
     # Check if the title label still exists
     if hasattr(self, 'title_label') and self.title_label.winfo_exists():
         current_color = self.title_label.cget("fg")
         next_color = "#FF5733" if current_color == "#007ACC" else "#007ACC"  # Alternate between colors
         self.title_label.config(fg=next_color)
         # Schedule the next color change
         self.root.after(500, self.animate_title)
     else:
         # If the title_label no longer exists, stop the animation
         return




    def show_register(self):
     """Show the registration form"""
     self.clear_window()
     
     # Set background color for the form
     cream_color = "#EBC7B2"
     self.root.configure(bg=cream_color)
     
     # Configure the grid to center all elements even if the window is resized
     self.root.grid_rowconfigure(0, weight=1)
     self.root.grid_rowconfigure(6, weight=1)
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(3, weight=1)
 
     # Title label, spans across all columns and centered
     title_label = tk.Label(self.root, text="Register", font=("Arial", 16, "bold"), bg=cream_color)
     title_label.grid(row=0, column=0, columnspan=3, pady=(20, 10))
 
     # Username field
     tk.Label(self.root, text="Username:", font=("Helvetica", 12), bg=cream_color).grid(row=1, column=0, padx=20, pady=10, sticky="e")
     self.reg_username = tk.Entry(self.root, font=("Helvetica", 12))
     self.reg_username.grid(row=1, column=1, padx=20, pady=10, sticky="w")
 
     # Password field
     tk.Label(self.root, text="Password:", font=("Helvetica", 12), bg=cream_color).grid(row=2, column=0, padx=20, pady=10, sticky="e")
     self.reg_password = tk.Entry(self.root, show="*", font=("Helvetica", 12))
     self.reg_password.grid(row=2, column=1, padx=20, pady=10, sticky="w")
 
     # Role selection
     tk.Label(self.root, text="Role:", font=("Helvetica", 12), bg=cream_color).grid(row=3, column=0, padx=20, pady=10, sticky="e")
     self.reg_role = tk.StringVar(value="student")
     role_frame = tk.Frame(self.root, bg=cream_color)  # Group radio buttons in a frame for better layout
     role_frame.grid(row=3, column=1, padx=20, pady=10, sticky="w")
     tk.Radiobutton(role_frame, text="Student", variable=self.reg_role, value="student", bg=cream_color, font=("Helvetica", 12)).pack(side="left", padx=5)
     tk.Radiobutton(role_frame, text="Instructor", variable=self.reg_role, value="instructor", bg=cream_color, font=("Helvetica", 12)).pack(side="left", padx=5)
 
     #Register button aligned properly  #sumit 2.30
     register_button = tk.Button(self.root, text="Register", font=("Helvetica", 12, "bold"), bg="#4CAF50", fg="white", 
                                 command=lambda: self.execute_with_leader(self.register), width=12)  
     register_button.grid(row=4, column=0, columnspan=2, pady=20, padx=20)
 
     # Back to login button aligned properly
     back_button = tk.Button(self.root, text="Back to Login", font=("Helvetica", 12, "bold"), bg="#2196F3", fg="white", 
                             command=self.show_login, width=12)
     back_button.grid(row=5, column=0, columnspan=2, pady=10, padx=20)
 
     # Add spacing between the bottom and the last button
     self.root.grid_rowconfigure(6, weight=1)
 
 
    def register(self, stub):
     """Register a new user (student or instructor) asynchronously"""
     username = self.reg_username.get()
     password = self.reg_password.get()
     role = self.reg_role.get()
 
     def send_register_request(stub, *args):
         return stub.Register(lms_pb2.RegisterRequest(username=username, password=password, role=role))
 
     try:
         # Process the register request using the leader stub asynchronously
         future = self.communicate_with_leader_async(send_register_request)
         self.executor.submit(self.process_register_response, future)
 
     except grpc.RpcError as e:
         if e.code() == grpc.StatusCode.UNAVAILABLE:
             messagebox.showerror("Error", "Leader server is unavailable. Please try again later.")
         else:
             messagebox.showerror("Error", f"Failed to register: {str(e)}")



    def process_register_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Registration Success", response.message)
             self.show_login()  # Go back to login after successful registration
         else:
             messagebox.showerror("Registration Failed", response.message)
     except Exception as e:
         messagebox.showerror("Error", f"Failed to register: {str(e)}")
 

    def login(self, stub):
     """Handle user login asynchronously"""
     username = self.username.get()
     password = self.password.get()
 
     def send_login_request(stub, *args):
         return stub.Login(lms_pb2.LoginRequest(username=username, password=password))
 
     # Process the login request using the leader stub
     future = self.communicate_with_leader_async(send_login_request)
     self.executor.submit(self.process_login_response, future)

 
 

    def process_login_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             self.token = response.token
             self.role = response.role
 
             if self.role == "instructor":
                 self.show_instructor_menu()  # Show the instructor menu
             elif self.role == "student":
                 self.show_student_menu()  # Show the student menu
         else:
             messagebox.showerror("Error", "Login failed. Please check your credentials.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to login: {str(e)}")


    
    def clear_window(self):
        """Clear the current window"""
        for widget in self.root.winfo_children():
            widget.destroy()

    def show_student_menu(self):
     """Menu for students"""
     self.clear_window()
     
     # Set background color for the menu
     cream_color = "#FFFDD0"
     self.root.configure(bg=cream_color)
     
     # Configure the grid to center all elements even if the window is resized
     self.root.grid_rowconfigure(0, weight=1)
     self.root.grid_rowconfigure(7, weight=1)
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(2, weight=1)
     
     # Title label, spans across all columns and centered
     title_label = tk.Label(self.root, text="Student Dashboard", font=("Arial", 16, "bold"), bg=cream_color)
     title_label.grid(row=0, column=0, columnspan=3, pady=(20, 10))
 
    # View Course Material button
     view_course_button = tk.Button(self.root, text="View Course Material", font=("Helvetica", 12, "bold"), bg="#4CAF50", fg="white",
                                    command=lambda: self.execute_with_leader(self.view_course_material), width=25)
     view_course_button.grid(row=1, column=1, pady=10)
 
     # Post Assignment button
     post_assignment_button = tk.Button(self.root, text="Post Assignment", font=("Helvetica", 12, "bold"), bg="#2196F3", fg="white",
                                        command=self.post_assignment, width=25)
     post_assignment_button.grid(row=2, column=1, pady=10)
 
     # View Grades button
     view_grades_button = tk.Button(self.root, text="View Grades", font=("Helvetica", 12, "bold"), bg="#FF9800", fg="white",
                                    command=lambda: self.execute_with_leader(self.view_grades), width=25)
     view_grades_button.grid(row=3, column=1, pady=10)
 
     # Ask Query button
     ask_query_button = tk.Button(self.root, text="Ask Query", font=("Helvetica", 12, "bold"), bg="#9C27B0", fg="white",
                                  command=self.ask_query, width=25)
     ask_query_button.grid(row=4, column=1, pady=10)
 
     # View Instructor Responses button
     view_responses_button = tk.Button(self.root, text="View Instructor Responses", font=("Helvetica", 12, "bold"), bg="#03A9F4", fg="white",
                                       command=lambda: self.execute_with_leader(self.view_instructor_responses), width=25)
     view_responses_button.grid(row=5, column=1, pady=10)
 
     # Logout button
     logout_button = tk.Button(self.root, text="Logout", font=("Helvetica", 12, "bold"), bg="#F44336", fg="white",
                               command=lambda: self.execute_with_leader(self.logout), width=25)
     logout_button.grid(row=6, column=1, pady=20)
 
     # Add spacing between the bottom and the last button
     self.root.grid_rowconfigure(7, weight=1)


    def show_instructor_menu(self):
     """Show instructor options."""
     self.clear_window()
     
     # Set background color for the menu
     cream_color = "#FFFDD0"
     self.root.configure(bg=cream_color)
     
     # Configure the grid to center all elements even if the window is resized
     self.root.grid_rowconfigure(0, weight=1)
     self.root.grid_rowconfigure(5, weight=1)
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(2, weight=1)
     
     # Title label, spans across all columns and centered
     title_label = tk.Label(self.root, text="Instructor Dashboard", font=("Arial", 16, "bold"), bg=cream_color)
     title_label.grid(row=0, column=0, columnspan=3, pady=(20, 10))
     
     # Post Course Material button
     post_course_button = tk.Button(self.root, text="Post Course Material", font=("Helvetica", 12, "bold"), bg="#4CAF50", fg="white",
                                    command=self.post_course_material, width=25)
     post_course_button.grid(row=1, column=1, pady=10)
     
     # View and Grade Assignments button
     grade_assignments_button = tk.Button(self.root, text="View and Grade Assignments", font=("Helvetica", 12, "bold"), bg="#FF9800", fg="white",
                                          command=self.view_and_grade_assignments, width=25)
     grade_assignments_button.grid(row=2, column=1, pady=10)
     
     # Respond to Query button
     respond_query_button = tk.Button(self.root, text="Respond to Query", font=("Helvetica", 12, "bold"), bg="#9C27B0", fg="white",
                                      command=lambda: self.execute_with_leader(self.respond_to_query), width=25)
     respond_query_button.grid(row=3, column=1, pady=10)
     
     # Logout button
     logout_button = tk.Button(self.root, text="Logout", font=("Helvetica", 12, "bold"), bg="#F44336", fg="white",
                               command=lambda: self.execute_with_leader(self.logout), width=25)
     logout_button.grid(row=4, column=1, pady=20)
     
     # Add spacing between the bottom and the last button
     self.root.grid_rowconfigure(5, weight=1)
 


        #STUDENT OPTIONS

    def view_course_material(self, stub):
     """View and download course material posted by the instructor asynchronously."""
     self.clear_window()
 
     def get_course_material(stub, *args):
         return stub.Get(lms_pb2.GetRequest(token=self.token, type="course_material"))
 
     try:
         # Process the course material request asynchronously using the leader stub
         future = self.communicate_with_leader_async(get_course_material)
         
         # Submit the result to be processed when the future is done
         self.executor.submit(self.process_view_course_material_response, future)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve course material: {str(e)}")




    def process_view_course_material_response(self, future):
     """Process the response for viewing course materials"""
     try:
         response = future.result()  # Wait for the result
         if response.success:
             if not response.entries:  # If no entries exist, check the message
                 messagebox.showinfo("Course Material", response.message)
                 self.show_student_menu()  # Go back to the student menu if no materials are available
                 return  # Exit early if no entries
 
             # Title for the course materials section
             tk.Label(self.root, text="Course Materials", font=("Arial", 16, "bold")).pack(pady=20)
 
             # Frame to hold the course materials
             materials_frame = tk.Frame(self.root, bg="#f0f0f0")  # Light background for contrast
             materials_frame.pack(pady=10, padx=10)
 
             row = 1  # Track row for dynamic UI layout
             for entry in response.entries:
                 instructor_name = entry.instructor if hasattr(entry, 'instructor') else "Unknown"
 
                 # Display instructor name and course material filename with a contrasting background
                 material_label = tk.Label(
                     materials_frame,
                     text=f"Instructor: {instructor_name}, File: {entry.filename}",
                     wraplength=400,
                     justify="left",
                     bg="#d1e7dd",  # Light green background for course material entry
                     fg="#0f5132",  # Dark green text for contrast
                     font=("Arial", 12),
                     padx=10,  # Padding inside the label
                     pady=5    # Padding inside the label
                 )
                 material_label.grid(row=row, column=0, sticky="w", padx=10, pady=5)
 
                 # Button to download the course material
                 download_button = tk.Button(
                     materials_frame,
                     text="Download",
                     command=lambda e=entry: self.download_course_material(e),
                     bg="#cce5ff",  # Light blue background
                     fg="#004085",  # Dark blue text
                     font=("Arial", 12, "bold")
                 )
                 download_button.grid(row=row, column=1, padx=10, pady=5)
 
                 row += 1  # Increment row for next course material
 
             # Go Back button
             tk.Button(
                 self.root,
                 text="Go Back",
                 command=self.show_student_menu,
                 width=15,
                 bg="lightgray",
                 font=("Arial", 12, "bold")
             ).pack(pady=20)
 
         else:
             messagebox.showerror("Error", "Failed to retrieve course material.")
             self.show_student_menu()
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve course material: {str(e)}")
         self.show_student_menu()

 

    def download_course_material(self, entry):
     """Download course material and ask where to save it."""
     save_path = asksaveasfilename(defaultextension=".pdf", initialfile=entry.filename, 
                                   title="Save Course Material", 
                                   filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")])
 
     if save_path:
         try:
             def download_course_material_data(stub, *args):
                 return stub.Get(lms_pb2.GetRequest(token=self.token, type="course_material"))
 
             # Make asynchronous call to download the course material
             future = self.communicate_with_leader_async(download_course_material_data)
 
             # Submit the future for processing the response and saving the file
             self.executor.submit(self.process_download_course_material_response, future, save_path)
 
         except Exception as e:
             messagebox.showerror("Error", f"Failed to save course material: {str(e)}")



    def process_download_course_material_response(self, future, save_path):
     try:
         response = future.result()  # Wait for the result
         if response.success and response.entries:
             with open(save_path, 'wb') as f:
                 f.write(response.entries[0].file)  # Write the file content to the chosen location
             messagebox.showinfo("Success", f"Course material saved to {save_path}")
         else:
             messagebox.showerror("Error", "Failed to download course material.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to save course material: {str(e)}")
 


    def post_assignment(self):
     """Post assignment by selecting a file"""
     self.clear_window()
 
     # Title for the post assignment section
     tk.Label(self.root, text="Post Assignment", font=("Arial", 16, "bold")).pack(pady=20)
 
     # Frame to hold the input fields
     input_frame = tk.Frame(self.root, bg="#f0f0f0")  # Light background for contrast
     input_frame.pack(pady=10, padx=10)
 
     # Label and entry for file path
     tk.Label(input_frame, text="Enter the file path:", bg="#f0f0f0", font=("Arial", 12)).grid(row=0, column=0, padx=5, pady=5)
     self.file_path = tk.Entry(input_frame, font=("Arial", 12), width=40)
     self.file_path.grid(row=0, column=1, padx=5, pady=5)
 
     # Submit button
     tk.Button(
         self.root,
         text="Submit",
         command=lambda: self.execute_with_leader(self.submit_assignment),
         width=15,
         bg="#cce5ff",  # Light blue background
         fg="#004085",  # Dark blue text
         font=("Arial", 12, "bold")
     ).pack(pady=10)
 
     # Go Back button
     tk.Button(
         self.root,
         text="Go Back",
         command=self.go_back,
         width=15,
         bg="lightgray",
         font=("Arial", 12, "bold")
     ).pack(pady=5)



    def submit_assignment(self, stub):
     """Submit assignment by posting the file to the leader server."""
     file_path = self.file_path.get()
 
     try:
         # Read the assignment file
         with open(file_path, 'rb') as f:
             file_data = f.read()
         filename = os.path.basename(file_path)
 
         def post_assignment(stub, *args):
             return stub.Post(lms_pb2.PostRequest(token=self.token, type="assignment", file=file_data, filename=filename))
 
         # Post the assignment asynchronously using the leader stub
         future = self.communicate_with_leader_async(post_assignment)
 
         # Submit the future to the executor for asynchronous handling
         self.executor.submit(self.process_submit_assignment_response, future)
 
     except FileNotFoundError:
         messagebox.showerror("Error", "File not found.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to post assignment: {str(e)}")



    def process_submit_assignment_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Success", "Assignment posted successfully.")
         else:
             messagebox.showerror("Error", "Failed to post assignment.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to post assignment: {str(e)}")


    # def view_grades(self, stub):
    #  """Fetch and view grades asynchronously from the leader server."""
     
    #  # Clear the window to display grade information
    #  self.clear_window()
 
    #  # Add title label with spacing and bright color
    #  title_label = tk.Label(self.root, text="View Grades", font=("Arial", 24), fg="blue", bg="white")
    #  title_label.grid(row=0, column=1, padx=20, pady=20)
 
    #  # Define a function to request grades from the server
    #  def get_grades(stub, *args):
    #      return stub.GetGrade(lms_pb2.GetGradeRequest(token=self.token))
 
    #  try:
    #      # Asynchronously communicate with the leader to get the grades
    #      future = self.communicate_with_leader_async(get_grades)
 
    #      # Add a loading label while grades are being fetched
    #      loading_label = tk.Label(self.root, text="Loading grades...", font=("Arial", 16), fg="green", bg="white")
    #      loading_label.grid(row=1, column=1, padx=20, pady=10)
 
    #      # Submit the future to the executor for handling the response asynchronously
    #      self.executor.submit(self.process_view_grades_response, future)
 
    #  except Exception as e:
    #      # Show error if the grade retrieval process fails
    #      messagebox.showerror("Error", f"Failed to retrieve grades: {str(e)}")
 
    #  # Add a 'Go Back' button with bright color and increased spacing
    #  back_button = tk.Button(self.root, text="Go Back", command=self.go_back, font=("Arial", 14), bg="yellow", fg="black")
    #  back_button.grid(row=2, column=1, padx=20, pady=20)


 


    # def process_view_grades_response(self, future):
    #  try:
    #      response = future.result()  # Wait for the result
    #      if response.success:
    #          if response.grade == "No grades available yet." or response.grade == "Grade not yet assigned":
    #              messagebox.showinfo("Grades", response.grade)
    #              return  # Do not clear the window if just showing a dialog
    #          else:
    #              self.clear_window()
    #              tk.Label(self.root, text="Your Grades", font=("Arial", 16)).grid(row=0, column=1)
    #              tk.Label(self.root, text=response.grade).grid(row=1, column=1)
 
    #              # Add "Go Back" button
    #              tk.Button(self.root, text="Go Back", command=self.go_back).grid(row=2, column=1)
    #      else:
    #          messagebox.showerror("Error", "Failed to retrieve grades.")
    #  except Exception as e:
    #      messagebox.showerror("Error", f"Failed to retrieve grades: {str(e)}")


    def view_grades(self, stub):
       """Fetch and view grades asynchronously from the leader server."""
       
       # Clear the window to display grade information
       self.clear_window()
       
       # Title label with bold font, padding, and background color
       title_label = tk.Label(
           self.root, 
           text="View Grades", 
           font=("Arial", 24, "bold"), 
           fg="#0d6efd",  # Blue text color for title
           bg="#f8f9fa"   # Light background color
       )
       title_label.grid(row=0, column=1, padx=20, pady=20)
   
       # Define a function to request grades from the server
       def get_grades(stub, *args):
           return stub.GetGrade(lms_pb2.GetGradeRequest(token=self.token))
   
       try:
           # Asynchronously communicate with the leader to get the grades
           future = self.communicate_with_leader_async(get_grades)
   
           # Loading label with subtle color indicating the process is ongoing
           loading_label = tk.Label(
               self.root, 
               text="Loading grades...", 
               font=("Arial", 14), 
               fg="#198754",  # Green text for loading status
               bg="#f8f9fa"
           )
           loading_label.grid(row=1, column=1, padx=20, pady=10)
   
           # Submit the future to the executor for handling the response asynchronously
           self.executor.submit(self.process_view_grades_response, future)
   
       except Exception as e:
           # Show error if the grade retrieval process fails
           messagebox.showerror("Error", f"Failed to retrieve grades: {str(e)}")
   
       # "Go Back" button with improved style and padding
       back_button = tk.Button(
           self.root, 
           text="Go Back", 
           command=self.go_back, 
           font=("Arial", 12, "bold"), 
           bg="#d1e7dd",   # Light green button background
           fg="#0f5132",   # Dark green text color
           width=15,       # Width for better appearance
           relief="raised"  # Raised effect for button style
       )
       back_button.grid(row=2, column=1, padx=20, pady=20)

    def process_view_grades_response(self, future):
       """Process the response for viewing grades."""
       try:
           response = future.result()  # Wait for the result
           if response.success:
               # Display message if grades are not yet available
               if response.grade in ["No grades available yet.", "Grade not yet assigned"]:
                   messagebox.showinfo("Grades", response.grade)
                   self.show_student_menu()
                   return
               
               # Clear window and display grades
               self.clear_window()
               
               # Header label for grade display
               tk.Label(
                   self.root, 
                   text="Your Grades", 
                   font=("Arial", 18, "bold"), 
                   fg="#0d6efd", 
                   bg="#f8f9fa"
               ).grid(row=0, column=1, pady=10)
   
               # Label for displaying the actual grade with distinct styling
               grade_label = tk.Label(
                   self.root, 
                   text=response.grade, 
                   font=("Arial", 14), 
                   fg="#0f5132",  # Dark green for grade text
                   bg="#d1e7dd",  # Light green background for grade display
                   relief="sunken",  # Sunken effect to make the grade stand out
                   padx=10,
                   pady=5
               )
               grade_label.grid(row=1, column=1, padx=20, pady=20)
   
               # "Go Back" button with consistent style
               back_button = tk.Button(
                   self.root, 
                   text="Go Back", 
                   command=self.go_back, 
                   font=("Arial", 12, "bold"), 
                   bg="#d1e7dd", 
                   fg="#0f5132", 
                   width=15, 
                   relief="raised"
               )
               back_button.grid(row=2, column=1, pady=20)
               
           else:
               messagebox.showerror("Error", "Failed to retrieve grades.")
               self.show_student_menu()
       except Exception as e:
           messagebox.showerror("Error", f"Failed to retrieve grades: {str(e)}")
           self.show_student_menu()
   




    def ask_query(self):
     """UI for students to ask a query to the instructor or LLM"""
     self.clear_window()
 
     # Set window title
     self.root.title("Ask a Query")
 
     # Instruction label for entering query
     instruction_label = tk.Label(self.root, text="Enter your query:")
     instruction_label.grid(row=0, column=0, padx=10, pady=10, sticky="e")
 
     # Entry for query text
     self.query_text = tk.Entry(self.root, width=50)
     self.query_text.grid(row=0, column=1, padx=10, pady=10, columnspan=2)
 
     # Label for query option selection
     option_label = tk.Label(self.root, text="Ask from Instructor or LLM?")
     option_label.grid(row=1, column=0, padx=10, pady=10, sticky="e")
 
     # Radio buttons for selecting instructor or LLM, with Instructor centered between the columns
     self.query_option = tk.StringVar(value="llm")
     instructor_radio = tk.Radiobutton(self.root, text="Instructor", variable=self.query_option, value="instructor")
     instructor_radio.grid(row=1, column=1, padx=10, pady=10, sticky="e")
     llm_radio = tk.Radiobutton(self.root, text="LLM", variable=self.query_option, value="llm")
     llm_radio.grid(row=1, column=2, padx=10, pady=10, sticky="w")
 
     # Frame for buttons to group them together and adjust spacing
     button_frame = tk.Frame(self.root)
     button_frame.grid(row=3, column=0, columnspan=3, pady=20)
 
     # Submit Query button
     submit_button = tk.Button(button_frame, text="Submit Query", 
                               command=lambda: self.execute_with_leader(self.submit_query), 
                               width=20, bg="lightblue", fg="black", font=("Arial", 10, "bold"))
     submit_button.grid(row=0, column=0, padx=15, pady=10)
 
     # Go Back button
     go_back_button = tk.Button(button_frame, text="Go Back", 
                                command=self.go_back, width=20, 
                                bg="lightgray", fg="black", font=("Arial", 10, "bold"))
     go_back_button.grid(row=0, column=1, padx=15, pady=10)
 
     # Adjust column configurations for better alignment
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(1, weight=1)
     self.root.grid_columnconfigure(2, weight=1)




    def submit_query(self, stub):
     """Send query to instructor or LLM based on user's choice asynchronously."""
     query = self.query_text.get()
     option = self.query_option.get()
 
     try:
         if option == "llm":
             def send_llm_query(stub, *args):
                 return stub.GetLLMAnswer(lms_pb2.QueryRequest(token=self.token, query=query))
 
             # Send the query to LLM asynchronously using the leader stub
             future = self.communicate_with_leader_async(send_llm_query)
             self.executor.submit(self.process_llm_query_response, future)
 
         elif option == "instructor":
             def send_instructor_query(stub, *args):
                 return stub.Post(lms_pb2.PostRequest(token=self.token, type="query", data=query))
 
             # Send the query to the instructor asynchronously using the leader stub
             future = self.communicate_with_leader_async(send_instructor_query)
             self.executor.submit(self.process_instructor_query_response, future)
     
     except Exception as e:
         messagebox.showerror("Error", f"Failed to submit query: {str(e)}")
 
 

    def process_llm_query_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("LLM Response", response.response)
         else:
             messagebox.showerror("Error", "Failed to retrieve answer from LLM.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve LLM answer: {str(e)}")
 

    def process_instructor_query_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Success", "Query sent to the instructor successfully.")
         else:
             messagebox.showerror("Error", "Failed to send query to the instructor.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to send query: {str(e)}")





    def view_instructor_responses(self, stub):
     """Student view for instructor's responses to their queries asynchronously."""
     self.clear_window()
 
     def get_instructor_responses(stub, *args):
         return stub.GetInstructorResponse(lms_pb2.GetRequest(token=self.token))
 
     try:
         # Send the request to get instructor responses asynchronously using the leader stub
         future = self.communicate_with_leader_async(get_instructor_responses)
         
         # Submit the future to the executor for handling the response asynchronously
         self.executor.submit(self.process_instructor_responses_response, future)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve instructor responses: {str(e)}")
 


    def process_instructor_responses_response(self, future):
     """Process the response for instructor responses"""
     try:
         response = future.result()  # Wait for the result
         if response.success:
             if not response.entries:
                 messagebox.showinfo("Responses", "No instructor responses available.")
                 self.show_student_menu()
                 return  # Do not clear the window if just showing a dialog
 
             # Title for the responses screen
             tk.Label(self.root, text="Instructor Responses", font=("Arial", 16, "bold")).pack(pady=20)
 
             # Frame to hold response labels
             response_frame = tk.Frame(self.root, bg="#f0f0f0")  # Light background for contrast
             response_frame.pack(pady=10, padx=10)
 
             # Display the responses
             for entry in response.entries:
                 response_label = tk.Label(
                     response_frame,
                     text=entry.data,
                     wraplength=400,
                     justify="left",
                     font=("Arial", 12),
                     bg="#d1e7dd",  # Light green background for response
                     fg="#0f5132",  # Dark green text for contrast
                     relief="sunken",  # Optional: Gives a raised effect
                     padx=10,  # Padding inside the label
                     pady=5  # Padding inside the label
                 )
                 response_label.pack(padx=10, pady=5, anchor="w")  # Padding and left alignment
 
             # Add "Go Back" button
             tk.Button(
                 self.root,
                 text="Go Back",
                 command=self.show_student_menu,
                 width=20,
                 bg="lightgray",
                 font=("Arial", 10, "bold")
             ).pack(pady=20)
 
         else:
             messagebox.showerror("Error", "Failed to retrieve responses.")
             self.show_student_menu()
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve responses: {str(e)}")
         self.show_student_menu()







    def go_back(self):
     """Go back to the student or instructor menu depending on the role"""
     if self.role == "student":
        self.show_student_menu()
     else:
        self.show_instructor_menu()



        #INSTRUCTOR OPTIONS


    #left
    def post_course_material(self):
     """UI for posting course material"""
     self.clear_window()
 
     # Set window title
     self.root.title("Post Course Material")
 
     # Title Label
     title_label = tk.Label(self.root, text="Post Course Material", font=("Arial", 16, "bold"))
     title_label.grid(row=0, column=0, columnspan=2, padx=20, pady=20)
 
     # File path label and entry
     file_label = tk.Label(self.root, text="Enter the file path:", font=("Arial", 12))
     file_label.grid(row=1, column=0, padx=10, pady=10, sticky="e")
 
     self.file_path = tk.Entry(self.root, width=50)
     self.file_path.grid(row=1, column=1, padx=10, pady=10)
 
     # Frame to hold the buttons (Submit and Go Back)
     button_frame = tk.Frame(self.root)
     button_frame.grid(row=2, column=0, columnspan=2, pady=20)
 
     # Submit Button
     submit_button = tk.Button(button_frame, text="Submit", 
                               command=lambda: self.execute_with_leader(self.submit_course_material), 
                               width=15, bg="lightblue", font=("Arial", 10, "bold"))
     submit_button.grid(row=0, column=0, padx=15, pady=10)
 
     # Go Back Button
     go_back_button = tk.Button(button_frame, text="Go Back", 
                                command=self.go_back, width=15, 
                                bg="lightgray", font=("Arial", 10, "bold"))
     go_back_button.grid(row=0, column=1, padx=15, pady=10)
 
     # Adjust column configurations for dynamic resizing
     self.root.grid_columnconfigure(0, weight=1)
     self.root.grid_columnconfigure(1, weight=1)




    def submit_course_material(self, stub):
     """Submit course material asynchronously by posting the file to the leader server."""
     file_path = self.file_path.get()
 
     try:
         # Read the course material file
         with open(file_path, 'rb') as f:
             file_data = f.read()
         filename = os.path.basename(file_path)
 
         def post_course_material(stub, *args):
             return stub.Post(lms_pb2.PostRequest(token=self.token, type="course_material", file=file_data, filename=filename))
 
         # Post the course material asynchronously using the leader stub
         future = self.communicate_with_leader_async(post_course_material)
 
         # Submit the future to the executor for asynchronous handling
         self.executor.submit(self.process_submit_course_material_response, future)
 
     except FileNotFoundError:
         messagebox.showerror("Error", "File not found.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to post course material: {str(e)}")



    def process_submit_course_material_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Success", "Course material posted successfully.")
         else:
             messagebox.showerror("Error", "Failed to post course material.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to post course material: {str(e)}")


    def view_and_grade_assignments(self):
     """Instructor view to download assignments and grade students asynchronously."""
     self.clear_window()
 
     def get_student_assignments(stub, *args):
         return stub.Get(lms_pb2.GetRequest(token=self.token, type="student_list"))
 
     try:
         # Send the request to get student assignments asynchronously using the leader stub
         future = self.communicate_with_leader_async(get_student_assignments)
 
         # Submit the future to the executor for processing the response
         self.executor.submit(self.process_view_and_grade_assignments_response, future)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve assignments: {str(e)}")



    def process_view_and_grade_assignments_response(self, future):
     """Process response for viewing and grading assignments"""
     try:
         response = future.result()  # Wait for the result
         if response.success:
             if not response.entries:
                 messagebox.showinfo("Student List", "No assignments left to grade.")
                 self.show_instructor_menu()  # Go back to the instructor menu if no assignments are available
                 return  # Exit early if no entries
 
             # Title for the grading screen
             tk.Label(self.root, text="Grade Assignments", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=5, pady=20)
 
             row = 1  # Track row for dynamic UI layout
             for entry in response.entries:
                 # Display student ID and assignment file name
                 tk.Label(self.root, text=f"Assignment from Student ID: {entry.id}", font=("Arial", 12)).grid(row=row, column=0, padx=10, pady=10, sticky="w")
                 tk.Label(self.root, text=f"File: {entry.filename}", font=("Arial", 12)).grid(row=row, column=1, padx=10, pady=10, sticky="w")
 
                 # Download assignment button
                 tk.Button(self.root, text="Download", command=lambda e=entry: self.execute_with_leader(lambda stub: self.download_assignment(stub, e)),
                           width=15, bg="lightblue", font=("Arial", 10, "bold")).grid(row=row, column=2, padx=10, pady=10)
 
                 # Grade label and entry
                 tk.Label(self.root, text="Enter Grade:", font=("Arial", 12)).grid(row=row, column=3, padx=10, pady=10, sticky="e")
                 grade_entry = tk.Entry(self.root, width=10)
                 grade_entry.grid(row=row, column=4, padx=10, pady=10)
 
                 # Submit grade button
                 tk.Button(self.root, text="Submit Grade", command=lambda e=entry, g=grade_entry: self.execute_with_leader(lambda stub: self.submit_grade(stub, e, g)),
                           width=15, bg="lightgreen", font=("Arial", 10, "bold")).grid(row=row, column=5, padx=10, pady=10)
 
                 row += 1  # Move to the next row for the next assignment
 
             # "Go Back" button at the bottom
             tk.Button(self.root, text="Go Back", command=self.show_instructor_menu, width=20, 
                       bg="lightgray", font=("Arial", 10, "bold")).grid(row=row, column=2, columnspan=2, pady=20)
 
         else:
             messagebox.showerror("Error", "Failed to retrieve student list.")
             self.show_instructor_menu()
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve student list: {str(e)}")
         self.show_instructor_menu()

 


    def download_assignment(self, stub, entry):
     """Download assignment file and ask where to save it."""
     save_path = asksaveasfilename(defaultextension=".pdf", initialfile=entry.filename, 
                                   title="Save Assignment", 
                                   filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")])
 
     if save_path:
         try:
             def download_assignment_data(stub, *args):
                 return stub.Get(lms_pb2.GetRequest(token=self.token, type="student_list"))
 
             # Send the request asynchronously to download the assignment using the leader stub
             future = self.communicate_with_leader_async(download_assignment_data)
 
             # Submit the future to the executor for processing the response asynchronously
             self.executor.submit(self.process_download_assignment_response, future, save_path)
 
         except Exception as e:
             messagebox.showerror("Error", f"Failed to save assignment: {str(e)}")



    def process_download_assignment_response(self, future, save_path):
     try:
         response = future.result()  # Wait for the result
         if response.success and response.entries:
             with open(save_path, 'wb') as f:
                 f.write(response.entries[0].file)  # Write the file content to the chosen location
             messagebox.showinfo("Success", f"Assignment saved to {save_path}")
         else:
             messagebox.showerror("Error", "Failed to download the assignment.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to save assignment: {str(e)}")


    def submit_grade(self, stub, entry, grade_entry):
     """Submit the grade for the student's assignment asynchronously."""
     grade = grade_entry.get()
     if not grade:
         messagebox.showerror("Error", "Please enter a grade before submitting.")
         return
 
     def submit_grade_request(stub, *args):
         return stub.GradeAssignment(lms_pb2.GradeRequest(token=self.token, studentId=entry.id, grade=grade))
 
     try:
         # Send the request asynchronously to submit the grade using the leader stub
         future = self.communicate_with_leader_async(submit_grade_request)
 
         # Submit the future to the executor for processing the response asynchronously
         self.executor.submit(self.process_submit_grade_response, future, entry.id, grade)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to submit grade: {str(e)}")

 
 
    def process_submit_grade_response(self, future, student_id, grade):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Success", f"Grade {grade} submitted for Student ID: {student_id}")
 
             # After grading, refresh the assignment list
             self.view_and_grade_assignments()
         else:
             messagebox.showerror("Error", "Failed to submit grade.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to submit grade: {str(e)}")






    def respond_to_query(self, stub):
     """UI for instructor to respond to student queries asynchronously."""
     self.clear_window()
 
     def get_unanswered_queries(stub, *args):
         return stub.GetUnansweredQueries(lms_pb2.GetRequest(token=self.token))
 
     try:
         # Send the request asynchronously to get unanswered queries using the leader stub
         future = self.communicate_with_leader_async(get_unanswered_queries)
 
         # Submit the future to the executor for processing the response asynchronously
         self.executor.submit(self.process_respond_to_query_response, future)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve unanswered queries: {str(e)}")



    def process_respond_to_query_response(self, future):
     """Process response for responding to student queries"""
     try:
         response = future.result()  # Wait for the result
         if response.success:
             if not response.entries:
                 messagebox.showinfo("Respond to Queries", "No unanswered queries.")
                 self.show_instructor_menu()  # Go back to the instructor menu if no queries are available
                 return  # Return early to avoid displaying a blank screen
 
             # Title for the respond to queries screen
             tk.Label(self.root, text="Respond to Queries", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=20)
 
             # Create a dictionary where the key is the student ID and query, and the value is just the query
             self.student_queries = {f"{entry.id}: {entry.data}": entry.id for entry in response.entries}
 
             # Dropdown to display queries
             tk.Label(self.root, text="Select Query to Respond:", font=("Arial", 12)).grid(row=1, column=0, padx=10, pady=10, sticky="e")
 
             self.selected_query = tk.StringVar(self.root)
             self.selected_query.set(list(self.student_queries.keys())[0])  # Set the first query as the default
             query_menu = tk.OptionMenu(self.root, self.selected_query, *self.student_queries.keys())
             query_menu.grid(row=1, column=1, padx=10, pady=10, sticky="w")
 
             # Input field for the response
             tk.Label(self.root, text="Enter Response:", font=("Arial", 12)).grid(row=2, column=0, padx=10, pady=10, sticky="e")
 
             self.query_response = tk.Entry(self.root, width=50)
             self.query_response.grid(row=2, column=1, padx=10, pady=10)
 
             # Frame to hold buttons (Submit and Go Back)
             button_frame = tk.Frame(self.root)
             button_frame.grid(row=3, column=0, columnspan=2, pady=20)
 
             # Submit Response button
             tk.Button(button_frame, text="Submit Response", command=lambda: self.execute_with_leader(self.submit_response),
                       width=20, bg="lightblue", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=10, pady=10)
 
             # Go Back button
             tk.Button(button_frame, text="Go Back", command=self.show_instructor_menu, 
                       width=20, bg="lightgray", font=("Arial", 10, "bold")).grid(row=0, column=1, padx=10, pady=10)
 
         else:
             messagebox.showerror("Error", "Failed to retrieve queries.")
             self.show_instructor_menu()  # Return to the instructor menu if there's an error
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to retrieve queries: {str(e)}")
         self.show_instructor_menu()



    def submit_response(self, stub):
     """Submit instructor's response to the selected query asynchronously."""
     # Get the selected query (which includes both student ID and query text)
     selected_query_key = self.selected_query.get()
 
     # Extract the student ID from the selected query (it's stored in self.student_queries)
     student_id = self.student_queries[selected_query_key]
 
     # Get the instructor's response
     response_text = self.query_response.get()
 
     def submit_instructor_response(stub, *args):
         return stub.RespondToQuery(lms_pb2.PostRequest(token=self.token, studentId=student_id, data=response_text))
 
     try:
         # Send the request asynchronously to submit the instructor's response using the leader stub
         future = self.communicate_with_leader_async(submit_instructor_response)
 
         # Submit the future to the executor for processing the response asynchronously
         self.executor.submit(self.process_submit_response_response, future)
 
     except Exception as e:
         messagebox.showerror("Error", f"Failed to send response: {str(e)}")



    def process_submit_response_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Success", "Response sent successfully.")
             self.show_instructor_menu()  # Go back to the instructor menu after submitting the response
         else:
             messagebox.showerror("Error", "Failed to send response.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to send response: {str(e)}")
 
 





    def logout(self, stub):
     """Handle user logout with leader re-election in case the leader is down."""
     def send_logout_request(stub, *args):
         return stub.Logout(lms_pb2.LogoutRequest(token=self.token))
 
     try:
         # Process the logout request using the leader stub asynchronously
         future = self.communicate_with_leader_async(send_logout_request)
         self.executor.submit(self.process_logout_response, future)
 
     except grpc.RpcError as e:
         if e.code() == grpc.StatusCode.UNAVAILABLE:
             messagebox.showerror("Error", "Leader server is unavailable. Trying to find the new leader...")
             try:
                 # Attempt to find a new leader and retry logout
                 self.get_leader()  # Refresh leader detection
                 future = self.communicate_with_leader_async(send_logout_request)
                 self.executor.submit(self.process_logout_response, future)
             except Exception as e:
                 messagebox.showerror("Error", f"Failed to log out after retrying: {str(e)}")
         else:
             messagebox.showerror("Error", f"Failed to log out: {str(e)}")


    def process_logout_response(self, future):
     try:
         response = future.result()  # Wait for the result
         if response.success:
             messagebox.showinfo("Logout", "Logged out successfully.")
             self.token = None
             self.role = None
             self.show_login()  # Show login after successful logout
         else:
             messagebox.showerror("Error", "Failed to log out.")
     except Exception as e:
         messagebox.showerror("Error", f"Failed to log out: {str(e)}")
 
 

if __name__ == "__main__":
    root = tk.Tk()
    app = LMSApp(root)
    root.mainloop()