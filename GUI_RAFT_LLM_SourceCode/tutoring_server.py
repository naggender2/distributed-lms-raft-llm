import grpc
from concurrent import futures
import time
import lms_pb2
import lms_pb2_grpc
from transformers import GPT2LMHeadModel, GPT2Tokenizer


# Load the pre-trained GPT-2 model and tokenizer
model_name = "gpt2"
model = GPT2LMHeadModel.from_pretrained(model_name)
tokenizer = GPT2Tokenizer.from_pretrained(model_name)

# Function to generate response using GPT-2
def generate_llm_response(query):

    # Provide additional context or instruction to the model
    prompt = f"You are an intelligent assistant. Answer the following question in detail:\nQuestion: {query}\nAnswer:"

    inputs = tokenizer.encode(prompt, return_tensors="pt")
    outputs = model.generate(
        inputs, 
        max_length=150, 
        num_return_sequences=1, 
        temperature=0.7,         # Increase randomness slightly
        top_k=50,                # Restrict to top 50 likely tokens
        top_p=0.9,               # Nucleus sampling with cumulative probability threshold
        repetition_penalty=1.2   # Penalize repetition of the same tokens
    )
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return response

class TutoringService(lms_pb2_grpc.Tutoring):
     def GetLLMAnswer(self, request, context):
        query = request.query
        response = generate_llm_response(query)
        return lms_pb2.QueryResponse(success=True, response=response)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    lms_pb2_grpc.add_TutoringServicer_to_server(TutoringService(), server)
    server.add_insecure_port('[::]:50054')  # Separate port for tutoring server
    server.start()
    print("Tutoring Server started on port 50054")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == "__main__":
    serve()
