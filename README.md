# Distributed LMS with LLM Tutoring & Raft Consistency

A robust, fault-tolerant Learning Management System (LMS) designed for distributed environments. This project integrates a lightweight language model (LLM) for real-time tutoring and implements the Raft consensus protocol to ensure data consistency across multiple servers. Built for the Advanced Operating Systems course, it showcases practical applications of distributed systems, RPC, and AI-driven assistance.

## Table of Contents

- [Project Overview](#project-overview)
- [Features](#features)
- [Why This Project?](#why-this-project)
- [System Architecture](#system-architecture)
- [Key Components](#key-components)
- [How It Works](#how-it-works)
- [Demo Video](#demo-video)
- [Setup Instructions](#setup-instructions)
- [Usage Guide](#usage-guide)

## Project Overview

This project implements a distributed LMS where students and instructors interact through a GUI client. The system supports assignment uploads, grading, course material sharing, and a query system powered by a lightweight LLM (GPT-2). To guarantee data consistency and high availability, all critical data (such as grades and progress) is synchronized across multiple servers using the Raft consensus protocol. The system is built using Python, gRPC for RPC communication, and Tkinter for the GUI.

## Features

- **Distributed Architecture:** Multiple LMS servers with leader election and log replication via Raft.
- **LLM Tutoring:** Real-time, context-aware responses to student queries using a lightweight GPT-2 model.
- **Fault Tolerance:** System remains operational and consistent even if some nodes fail.
- **Rich Interactions:** Students can submit assignments, ask questions, and view grades; instructors can upload materials, grade, and respond to queries.
- **GUI Client:** User-friendly interface for both students and instructors.
- **PDF Handling:** Assignments and course materials are managed as PDF files.
- **Semantic Query Validation:** Student queries are checked for relevance to their assignments using BERT embeddings and cosine similarity.

## Why This Project?

- **Demonstrates Distributed Systems Concepts:** Showcases leader election, log replication, and fault tolerance using Raft.
- **Integrates Modern AI:** Provides real-time tutoring with a local LLM, enhancing the learning experience.
- **Ensures Data Consistency:** Critical data is always consistent across all nodes, even in the presence of failures.
- **Practical Application:** Simulates a real-world LMS with advanced features, making it a valuable educational tool for understanding distributed operating systems.

## System Architecture

- **Client Nodes:** GUI application for students and instructors.
- **LMS Servers:** Multiple instances, one acting as Raft leader, others as followers.
- **Tutoring Server:** Dedicated node running a lightweight GPT-2 model for AI-powered tutoring.
- **gRPC Communication:** All interactions use gRPC for efficient, language-agnostic RPC.
- **Raft Consensus:** Ensures that grades and progress are replicated and consistent across all LMS servers.

## Key Components

| Component         | Description                                                                 |
|-------------------|-----------------------------------------------------------------------------|
| `lms.proto`       | Protocol buffer definitions for all RPCs and data structures                |
| `lms_server.py`   | Main server logic, including Raft protocol and LMS operations               |
| `lms_gui_final.py`| Tkinter-based GUI client for user interaction                               |
| `tutoring_server.py` | LLM server using GPT-2 for answering student queries                     |
| `lms_pb2.py`, `lms_pb2_grpc.py` | Auto-generated gRPC code from proto definitions               |
| `Report.txt`     | Project report and design documentation                                      |


## How It Works

1. **User Authentication:** Students and instructors log in via the GUI client.
2. **Assignment Workflow:** Students upload assignments (PDFs); instructors download, grade, and provide feedback.
3. **Course Material Sharing:** Instructors upload course materials for students to access.
4. **Query System:** Students can ask questions, choosing between LLM or instructor responses.
   - If LLM is chosen, the query is checked for relevance to the assignment using BERT embeddings and cosine similarity.
   - If relevant, the query is forwarded to the tutoring server (GPT-2) for a detailed answer.
5. **Data Consistency:** All critical operations (e.g., grading) are replicated across all LMS servers using Raft, ensuring consistency and fault tolerance.
6. **Leader Election:** If the leader server fails, Raft automatically elects a new leader, and the system continues without data loss.

## Demo Video

A full demonstration of the system, including distributed setup, GUI interactions, and LLM-based tutoring, is available:

**[Project Demo Video](https://drive.google.com/file/d/15P_hOyWWGB91ECmnMVnaSa0G2aQIvv6b/view?usp=sharing)**

## Setup Instructions

### Prerequisites

- **Python 3.9 or higher**
- **Required Libraries:**
  - grpcio
  - grpcio-tools
  - tkinter (usually included with Python)
  - transformers
  - protobuf
  - PyPDF2
  - torch

Install dependencies:
```bash
pip install grpcio grpcio-tools transformers protobuf PyPDF2 torch
```

### Steps to Run

1. **Generate gRPC Code (if needed)**
   ```bash
   python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. lms.proto
   ```

2. **Configure Server Addresses**
   - Edit the IP addresses in `lms_gui_final.py` and `lms_server.py` to match your deployment setup.

3. **Run LMS Servers (on separate machines or terminals)**
   - Example commands (adjust IPs/ports as needed):
     ```bash
     python lms_server.py 1 50051 <peer1> <peer2> <peer3> <peer4>
     python lms_server.py 2 50052 <peer1> <peer2> <peer3> <peer4>
     # ...repeat for all 5 servers
     ```


4. **Run the Tutoring Server**
   ```bash
   python tutoring_server.py
   ```

5. **Run the GUI Client**
   ```bash
   python lms_gui_final.py
   ```

## Usage Guide

- **Login/Register:** Start the GUI client and log in as a student or instructor.
- **Students:**
  - Upload assignments (PDF).
  - Ask queries (choose LLM or instructor).
  - View grades and instructor responses.
  - Download course materials.
- **Instructors:**
  - Upload course materials.
  - Download and grade student assignments.
  - Respond to student queries.
- **LLM Tutoring:**
  - When a student asks a query to the LLM, the system checks if the query is relevant to their assignment using BERT embeddings.
  - If relevant, the query is sent to the GPT-2 server for a detailed answer.

