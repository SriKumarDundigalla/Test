import os
import PyPDF2
import openai
import tiktoken
from dotenv import load_dotenv
import logging
import nbformat
import jsonpatch
from openai import OpenAI
from Prompt_examples import output_quetions_format
# class Learning_Outcomes(BaseModel):
#     learning_outcomes : List[str] = Field(description="list of learning outcomes")
import matplotlib.pyplot as plt
import networkx as nx
# Load environment variables from the .env file
import community as community_louvain

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
import warnings
import shutil
import json
from langchain_text_splitters import TokenTextSplitter
from typing import List
from langchain.output_parsers import PydanticOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import logging
import nbformat
import PyPDF2
import ast
warnings.filterwarnings("ignore")
# Configure basic logging
logging.basicConfig(filename='app_Zeroshot.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def analyze_directory(directory):
    """
    Analyzes the content of the given directory and returns details of specific file types.

    :param directory: The path of the directory to analyze.
    :return: A list of dictionaries, each containing 'name', 'type', 'size', and 'path' of the file.
    """
    logging.info(f"Analyzing directory: {directory}")
    supported_extensions = {'.md', '.ipynb','.pdf'} #'.py'
    file_details = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            extension = os.path.splitext(file_path)[1]

            if extension in supported_extensions:
                file_info = {
                    'name': file,
                    'type': extension,
                    'size': os.path.getsize(file_path),
                    'path': file_path
                }
                file_details.append(file_info)
                logging.info(f"File added for processing: {file_path}")

    return file_details


def clean_content(content):
    """
    Performs cleaning of the file content, including trimming whitespace and removing non-printable characters.
    :param content: Raw content string to be cleaned.
    :return: Cleaned content string.
    """
    content = content.strip()  # Remove leading and trailing whitespace
    content = content.replace('\x00', '')  # Remove null bytes if present
    # Normalize line breaks and whitespace
    content = content.replace('\n', ' ')  # Replace new lines with spaces
    content = re.sub(r'\s+', ' ', content)  # Replace multiple spaces with a single space

    # Remove non-printable characters
    content = ''.join(char for char in content if char.isprintable() or char in ('\n', '\t', ' '))
    # Remove non-printable characters, including the replacement character
    content = re.sub(r'[^\x20-\x7E]+', '', content)
    return content

def read_file_content(file_info):
    """
    Reads the content of a file based on its type and returns the cleaned content as a string.
    :param file_info: Dictionary containing the file's details.
    :return: Cleaned content of the file as a string.
    """
    file_path = file_info['path']
    file_type = file_info['type']
    content = ''

    try:
        if file_type == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    page_text = page.extract_text() if page.extract_text() else ''
                    content += clean_content(page_text)
        elif file_type == '.ipynb':
            with open(file_path, 'r', encoding='utf-8') as f:
                nb = nbformat.read(f, as_version=4)
                for cell in nb.cells:
                    cell_content = cell.source + '\n\n'  # Add cell content
                    content += clean_content(cell_content)
        else:  # Assuming '.py' or other plaintext files
            with open(file_path, 'r', encoding='utf-8') as f:
                content = clean_content(f.read())

        logging.info(f"Successfully read and cleaned content from: {file_path}")
    except Exception as e:
        logging.exception(f"Error reading {file_path}: {e}")

    return content


def get_file_contents(file_details):
    """
    Retrieves the contents of each file based on the provided file details.

    :param file_details: List of dictionaries containing file details.
    :return: A list of dictionaries, each containing 'path' and 'content' of the file.
    """
    content_details = []
    for file_info in file_details:
        file_content = read_file_content(file_info)
        if file_content:
            content_details.append({
                'path': file_info['path'],
                'content': file_content
            })

    return content_details
def process_and_insert_contents(file_contents, persist_directory):
    """
    Processes the contents of each file, splits them, embeds, and inserts into a database.

    :param file_contents: List of dictionaries containing file paths and their contents.
    :param persist_directory: The directory to persist any necessary data for database insertion.
    """
    # Initialize the text splitter and embedding tools
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150,length_function=len)
    embedding = OpenAIEmbeddings()
    all_page_contents = []  # Collect all page contents for further processing or analysis
    # Extract page_content from each Document
    for content_detail in file_contents:
        # Split the content
        documents  = text_splitter.create_documents([content_detail['content']])
        for document in documents:
            page_content = document.page_content
            print(page_content)
            return  # Accessing the page_content attribute
            all_page_contents.append(page_content)
        # Here, you would generate embeddings and insert them into your database
        # This is a placeholder to illustrate the process
        vectordb = Chroma.from_documents(
            documents=documents,
            embedding=embedding,
            persist_directory=persist_directory
        )
        
        # Logging or any other operation after insertion
        logging.info(f"Processed and inserted content from: {content_detail['path']}")
    return vectordb
def summarize_files(file_details):
    """
    Processes the content of files whose content exceeds a specified global token size,
    by splitting the content into chunks. Each chunk's size is determined to ensure it 
    doesn't exceed the global token size limit. The function returns a list of dictionaries 
    with the filename/path, chunked content, and the token size of each chunk.

    :param file_details: List of dictionaries with file details.
    :return: A list of dictionaries with filename/path and chunked content.
    """
    global_token_size = int(os.getenv('GLOBAL_TOKEN_SIZE'))
    Overlap = 500  # Example overlap size, adjust as needed
    summarized_files = []

    for file in file_details:
        original_token_count = len(tiktoken.encoding_for_model("gpt-4").encode(file['content']))

        if original_token_count > global_token_size:
            # Calculate the number of chunks needed
            N = 1 + (original_token_count - global_token_size) // (global_token_size - Overlap)

            # Initialize the splitter with calculated chunk size and overlap
            splitter = RecursiveCharacterTextSplitter( chunk_size = original_token_count // N ,  chunk_overlap = Overlap, length_function=len, is_separator_regex=False)
            # Split the content into documents/chunks
            documents = splitter.create_documents([file['content']])
            for document in documents:
                summarized_files.append({
                        'content': document.page_content,
                        'token_size': len(tiktoken.encoding_for_model("gpt-4").encode(document.page_content))
                    })   
        else:
            # If the content does not exceed global token size, add it directly
            summarized_files.append({
                'path': file['path'],
                'content': file['content'],
                'token_size': original_token_count
            })

    return summarized_files

def create_chunks_from_content_greedy(file_contents, context_window_size):
    """
    Creates content chunks from a list of file content dictionaries using a Greedy approach, 
    ensuring that each chunk does not exceed a specified context window size in terms of tokens.

    Parameters:
    - file_contents (list of dict): A list of dictionaries, where each dictionary contains 
      'content' (str) and 'token_size' (int) keys. 'content' is the text of the file, and 
      'token_size' is the number of tokens that text consists of.
    - context_window_size (int): The maximum number of tokens that a single chunk can contain. 
      It defines the upper limit for the size of each content chunk.

    Returns:
    - list of str: A list of content chunks, where each chunk is a string composed of file contents 
      that together do not exceed the context window size. Each content is enclosed in triple backticks.
    """
    all_chunks = []  # Initialize the list to hold all content chunks
    current_chunk = ""  # Initialize the current chunk as an empty string
    current_token_count = 0  # Initialize the current token count to 0

    # Sort file_contents by 'token_size' in descending order
    sorted_file_contents = sorted(file_contents, key=lambda x: x['token_size'], reverse=True)

    for content in sorted_file_contents:
        # If adding this content exceeds the context window size, start a new chunk
        if current_token_count + content['token_size'] > context_window_size:
            if current_chunk:  # Ensure the current chunk is not empty
                all_chunks.append(current_chunk)  # Add the current chunk to all_chunks
                current_chunk = ""  # Reset the current chunk
                current_token_count = 0  # Reset the token count for the new chunk

        # Add the content to the current chunk if it fits, enclosed in triple backticks
        if current_token_count + content['token_size'] <= context_window_size:
            current_chunk += "\n" +"```" + content['content'] + "```" + "\n"  # Enclose content in backticks and append with a newline for readability
            current_token_count += content['token_size']
    
    # Add the last chunk if it contains any content, ensuring it's also enclosed in backticks
    if current_chunk:
        all_chunks.append(current_chunk)

    return all_chunks

    
def extract_key_topic(outcome):
    ignore_words = {"understand", "develop", "analyze", "the", "of", "using", "with", "for", "to", "and", "basic", "fundamentals"}
    words = re.sub(r'[^\w\s]', '', outcome.lower()).split()
    significant_words = [word for word in words if word not in ignore_words and len(word) > 4]
    
    # If after filtering there are multiple words, attempt to form a phrase that makes sense
    if len(significant_words) > 1:
        # Prioritize the last two words, often more specific in educational content
        return " ".join(significant_words[-2:])
    elif significant_words:
        return significant_words[0]
    else:
        return "General"

import networkx as nx
import matplotlib.pyplot as plt
import random
from matplotlib.lines import Line2D
from community import community_louvain
from itertools import cycle

    
import plotly.graph_objects as go
import networkx as nx
from sentence_transformers import SentenceTransformer
import numpy as np

#  # Define your desired data structure for learning outcomes.
# class LearningOutcomes(BaseModel):
#     outcomes: List[str] = Field(description="List of learning outcomes")
#  # Set up a parser to enforce the output structure.
# parser = PydanticOutputParser(pydantic_object=LearningOutcomes)

def generate_learning_outcomes_for_chunks(documents):
    api_key = os.getenv('OPENAI_API_KEY')
    delimiter = "###"
    chunk_LOs = {}  # Dictionary to hold learning outcomes for each chunk

    # Initialize OpenAI client with your API key
    client = openai.OpenAI(api_key=api_key)

    # The number of outcomes to generate per chunk, adjust as needed or dynamically set
    number_of_outcomes = int(os.getenv('LOs_PER_CHUNK', 5))

    
    system_message = f"""
      As a Professor with expertise in curriculum development and crafting learning outcomes, 
      your task is to extract and enumerate {number_of_outcomes} distinct learning outcomes from the 
      provided course content. This content includes programming code, with each topic or code example 
      distinctly separated by triple backticks ```. Your challenge is to recognize and interpret these 
      segmented topics, especially those conveyed through programming code, to determine their thematic 
      and practical contributions to the course. These outcomes should address the comprehensive skills 
      and knowledge base essential to the subject matter, with a special emphasis on the interpretation 
      and application of programming concepts as demonstrated within the code segments. 
      The learning outcomes should be formatted as a Python list, precisely containing {number_of_outcomes} 
      entries. Each entry must represent a unique learning outcome that students are expected to achieve by 
      the end of the course, directly informed by the theoretical content and the 
      practical programming code examples provided.
    """
    all_out_comes=[]


    for index, chunk in enumerate(documents):

        user_message = f"""
                        \"\"\"
                        As a curriculum developer and professor, I am tasked with creating learning outcomes based on the provided educational material. Below is a segment of educational content enclosed within triple backticks, which spans a wide range of topics potentially including theoretical discussions, practical applications, programming examples, and other forms of academic content. My goal is to distill this material into specific, actionable learning outcomes that reflect the essential skills and knowledge students are expected to master. 

                        Please generate learning outcomes for the following content:

                        {delimiter}{chunk}{delimiter}

                        The learning outcomes should be comprehensive, covering both conceptual understanding and applicable skills directly derived from the course content. Each outcome should be unique and relevant to the provided material.
                        \"\"\"
                        """

        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_message.strip()},
                {"role": "user", "content": user_message.strip()}
            ],
            temperature=0
        )
        
        summary = response.choices[0].message.content
        start = summary.find("[")
        end = summary.rfind("]") + 1
        outcome_list = eval(summary[start:end])
        all_out_comes.append(outcome_list)

    # Flatten each list of outcomes into a single string per list to simplify the example
    documents = [item for outcome_list in all_out_comes for item in outcome_list]
    # Load a pre-trained model
    return documents

def find_most_relevant_learning_outcome_document(vectordb, learning_outcomes):
    """
    Uses vectordb to find the most relevant learning outcome document from the database for each topic.

    :param vectordb: The vectordb instance configured for retrieval.
    :param learning_outcomes: A list of lists, where each sublist represents learning outcomes related to a specific topic.
    :return: A list of tuples, each containing the most relevant document's content and its relevance score for each list of learning outcomes.
    """
    # Initialize the vectordb retriever with 'k' set to 1 to retrieve the most relevant document
    retriever = vectordb.as_retriever(search_type="mmr", search_kwargs={"k": 1})

    documents=[]
    for LOS in learning_outcomes:
        outcome_page_mapping={}
        for i in LOS:
            docs = retriever.get_relevant_documents(i)
            outcome_page_mapping[i]=docs[0].page_content
        documents.append(outcome_page_mapping)
    return documents

def format_learning_outcomes_with_identifiers(learning_outcomes):
    formatted_strings = []
    outcome_counter = 1  # Initialize counters for learning outcomes
    api_key = os.getenv('OPENAI_API_KEY')
    client = openai.OpenAI(api_key=api_key)
    for outcome in learning_outcomes:
        formatted_string=""
        for key, value in outcome.items():
            # Format string with counters
            formatted_string = f"learning_outcome_{outcome_counter}: {key}\nrelated_content_{outcome_counter}: {value}\n"
            outcome_counter += 1  # Increment the learning outcome counter
        formatted_strings.append(formatted_string)
    system_message=f"""
                    You are a professor tasked with developing a concise series of multiple-choice quiz questions for your students, each aligned with a distinct learning outcome and directly related to specific content. Your objective is to ensure that each question not only integrates with the learning material but also that its correct answer is unequivocally found within the provided content. To accomplish this, follow the enhanced approach detailed below, which includes steps for identifying a similar main heading to unify the theme of your quiz.
                    **Enhanced Steps to Follow:**

                    1. **Synthesize the Core Theme:**
                    - Identify and define a central theme that encapsulates all six learning outcomes and their associated content. This theme will be the focal point of your quiz, guiding the formulation of questions and answers.

                    2. **Broaden the Theme with a Supplementary Heading:**
                    - Expand the quiz's scope by incorporating a supplementary theme that complements the core theme. This additional perspective should still connect directly to the six learning outcomes, enriching the quiz's thematic depth.

                    3. **Analyze Learning Outcomes and Related Content:**
                    - Thoroughly review each of the six learning outcomes and their corresponding content. Aim to extract key insights and knowledge that are essential to the core and supplementary themes, ensuring a comprehensive understanding that will be reflected in the quiz questions.

                    4. **Craft Themed Multiple-Choice Questions:**
                    - Create six multiple-choice questions, one for each learning outcome, that highlight critical aspects of the related content. Each question should align with both the core and supplementary themes, maintaining thematic consistency throughout the quiz.

                    5. **Select Correct Answers and Design Distractors:**
                    - Choose the correct answer for each question based on the related content. Then, develop three distractors for each question. These distractors should be relevant and plausible but incorrect, according to the content, ensuring the quiz accurately assesses the learner's understanding of the themes.

                    6. **Ensure Verification of Output:**
                    - Verify that the output (the quiz) includes six multiple-choice questions that adhere to the guidelines above. Each question should be clearly linked to one of the learning outcomes and accurately reflect both the core and supplementary themes.

                    This structured approach ensures each quiz question is directly tied to a learning outcome and related content, with a clear thematic link and verified structure for assessing learners' understanding.
                     
                    **Implementation Directive:**
                        If you are working with 6 learning outcomes and their related content, this process will result in 6 multiple-choice questions. Each question is tailored to its corresponding learning outcome, maintaining a strict one-to-one ratio between learning outcomes and questions, thereby ensuring a focused and effective evaluation of student understanding within the context of the similar main heading.

                    **Example Output Format:**

                        "Artificial Intelligence Essentials": "**1. What is Artificial Intelligence (AI)?**\nA) The simulation of human intelligence in machines\nB) A new internet technology\nC) A database management system\nD) A type of computer hardware\n**Answer: A) The simulation of human intelligence in machines**\n\n**2. Which of the following is a primary application of AI?**\nA) Data storage\nB) Speech recognition\nC) Website hosting\nD) Network cabling\n**Answer: B) Speech recognition**\n\n**3. What is a Neural Network?**\nA) A social media platform\nB) A computer system modeled on the human brain\nC) A new programming language\nD) A cybersecurity protocol\n**Answer: B) A computer system modeled on the human brain**\n\n**4. What does 'Natural Language Processing' (NLP) enable computers to do?**\nA) Increase processing power\nB) Understand and interpret human language\nC) Cool down servers\nD) Connect to the internet\n**Answer: B) Understand and interpret human language**\n\n**5. What is 'machine vision'?**\nA) A new type of display technology\nB) The ability of computers to 'see' and process visual data\nC) A marketing term for high-resolution screens\nD) A feature in video games\n**Answer: B) The ability of computers to 'see' and process visual data** "\n\n**6. How does AI impact the field of Robotics?**\nA) By reducing the cost of computer hardware\nB) By enabling robots to learn from their environment and improve their tasks\nC) By increasing the weight of robots\nD) By decreasing the need for internet connectivity\n**Answer: B) By enabling robots to learn from their environment and improve their tasks**"

                        "Data Science Introduction": "**1. What is the primary purpose of data analysis?**\nA) To store large amounts of data\nB) To transform data into meaningful insights\nC) To create visually appealing data presentations\nD) To increase data storage capacity\n**Answer: B) To transform data into meaningful insights**\n\n**2. Which programming language is most commonly used in data science?**\nA) Java\nB) Python\nC) C++\nD) JavaScript\n**Answer: B) Python**\n\n**3. What is a DataFrame in the context of data science?**\nA) A method to secure data\nB) A 3D representation of data\nC) A data structure for storing data in tables\nD) A type of database\n**Answer: C) A data structure for storing data in tables**\n\n**4. What does 'machine learning' refer to?**\nA) The process of programming machines to perform tasks\nB) The ability of a machine to improve its performance based on previous results\nC) The science of making machines that require energy\nD) The study of computer algorithms that improve automatically through experience\n**Answer: D) The study of computer algorithms that improve automatically through experience**\n\n**5. What is 'big data'?**\nA) Data that is too large to be processed by traditional databases\nB) A large amount of small datasets\nC) Data about big things\nD) A type of data visualization\n**Answer: A) Data that is too large to be processed by traditional databases**"\n\n**6. What role does data visualization play in data science?**\nA) To make databases run faster\nB) To improve data storage efficiency\nC) To represent data in graphical format for easier interpretation\nD) To encrypt data for security\n**Answer: C) To represent data in graphical format for easier interpretation**"
  
                        "Web Development Fundamentals": "**1. Which language is primarily used for structuring web pages?**\nA) CSS\nB) JavaScript\nC) HTML\nD) Python\n**Answer: C) HTML**\n\n**2. What does CSS stand for?**\nA) Cascading Style Scripts\nB) Cascading Style Sheets\nC) Computer Style Sheets\nD) Creative Style Sheets\n**Answer: B) Cascading Style Sheets**\n\n**3. What is the purpose of JavaScript in web development?**\nA) To add interactivity to web pages\nB) To structure web pages\nC) To style web pages\nD) To send data to a server\n**Answer: A) To add interactivity to web pages**\n\n**4. Which HTML element is used to link a CSS stylesheet?**\nA) <script>\nB) <link>\nC) <css>\nD) <style>\n**Answer: B) <link>**\n\n**5. What does AJAX stand for?**\nA) Asynchronous JavaScript and XML\nB) Automatic JavaScript and XML\nC) Asynchronous Java and XML\nD) Automatic Java and XML\n**Answer: A) Asynchronous JavaScript and XML**"\n\n**6. What is responsive web design?**\nA) Designing websites to respond to user behavior and environment based on screen size, platform, and orientation\nB) A design technique to make web pages load faster\nC) Creating web pages that respond to voice commands\nD) Developing websites that automatically update content\n**Answer: A) Designing websites to respond to user behavior and environment based on screen size, platform, and orientation**"\n\n**6. What is the difference between a virus and a worm?**\nA) A virus requires human action to spread, whereas a worm can propagate itself\nB) A worm is a type of antivirus software\nC) A virus can only affect data, not hardware\nD) Worms are beneficial software that improve system performance\n**Answer: A) A virus requires human action to spread, whereas a worm can propagate itself**"

                        "Cybersecurity Basics": "**1. What is the primary goal of cybersecurity?**\nA) To create new software\nB) To protect systems and networks from digital attacks\nC) To improve computer speed\nD) To promote open-source software\n**Answer: B) To protect systems and networks from digital attacks**\n\n**2. What is phishing?**\nA) A technique to fish information from the internet\nB) A cyberattack that uses disguised email as a weapon\nC) A firewall technology\nD) A data analysis method\n**Answer: B) A cyberattack that uses disguised email as a weapon**\n\n**3. What does 'encryption' refer to in the context of cybersecurity?**\nA) Converting data into a coded format to prevent unauthorized access\nB) Deleting data permanently\nC) Copying data to a secure location\nD) Monitoring data access\n**Answer: A) Converting data into a coded format to prevent unauthorized access**\n\n**4. What is a VPN used for?**\nA) Increasing internet speed\nB) Protecting online privacy and securing internet connections\nC) Creating websites\nD) Developing software\n**Answer: B) Protecting online privacy and securing internet connections**\n\n**5. What is malware?**\nA) Software used to perform malicious actions\nB) A new programming language\nC) A data analysis tool\nD) A type of computer hardware\n**Answer: A) Software used to perform malicious actions**"\n\n**6. What is the difference between a virus and a worm?**\nA) A virus requires human action to spread, whereas a worm can propagate itself\nB) A worm is a type of antivirus software\nC) A virus can only affect data, not hardware\nD) Worms are beneficial software that improve system performance\n**Answer: A) A virus requires human action to spread, whereas a worm can propagate itself**"

                        "Cloud Computing Fundamentals": "**1. What is cloud computing?**\nA) Storing and accessing data over the internet\nB) Predicting weather patterns\nC) Computing at high altitudes\nD) A new web development framework\n**Answer: A) Storing and accessing data over the internet**\n\n**2. Which of the following is a benefit of cloud computing?**\nA) Reduced IT costs\nB) Increased data loss\nC) Slower internet speeds\nD) More hardware requirements\n**Answer: A) Reduced IT costs**\n\n**3. What is SaaS?**\nA) Software as a Service\nB) Storage as a System\nC) Security as a Software\nD) Servers as a Service\n**Answer: A) Software as a Service**\n\n**4. What does 'scalability' mean in the context of cloud computing?**\nA) Decreasing the size of databases\nB) The ability to increase or decrease IT resources as needed\nC) The process of moving to a smaller server\nD) Reducing the number of cloud services\n**Answer: B) The ability to increase or decrease IT resources as needed**\n\n**5. What is a 'public cloud'?**\nA) A cloud service that is open for anyone to use\nB) A weather phenomenon\nC) A private network\nD) A type of VPN\n**Answer: A) A cloud service that is open for anyone to use**"\n\n**6. What is IaaS?**\nA) Internet as a Service\nB) Infrastructure as a Service\nC) Information as a System\nD) Integration as a Service\n**Answer: B) Infrastructure as a Service**"

                    **Proceed with this format for all questions, and is answerable based on the provided content. This comprehensive approach ensures a focused, educational, and thematic quiz that effectively assesses students' understanding and engagement with the material.** 
                """
    Quetions=[]
    for i in formatted_strings:
        user_message = f"Create multiple-choice questions based on the specified learning outcomes and their associated content within triple hashtags . Content details are provided below: ###{i}###."
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_message.strip()},
                {"role": "user", "content": user_message.strip()}
            ],
            temperature=0
        )
        
        summary = response.choices[0].message.content
        Quetions.append(summary)
    return Quetions
        

def remove_old_database_files(directory_path='./docs/chroma'):
    """
    Removes the specified directory and all its contents.

    :param directory_path: Path to the directory to be removed.
    """
    try:
        # Check if the directory exists
        if os.path.exists(directory_path) and os.path.isdir(directory_path):
            # Remove the directory and all its contents
            shutil.rmtree(directory_path)
            logging.info(f"Successfully removed directory: {directory_path}")
        else:
            logging.info(f"Directory does not exist, no need to remove: {directory_path}")
    except Exception as e:
        logging.exception(f"Error removing directory {directory_path}: {e}")

def generate_markdown_file(Quetions):
    api_key = os.getenv('OPENAI_API_KEY')
    client = openai.OpenAI(api_key=api_key)
    Content = "\n".join(Quetions)
    system_message = f"""

    You are tasked with creating a markdown document that efficiently organizes and presents given input content. Utilize your expertise in markdown formatting to structure this document according to the specified guidelines. Perform the following actions to achieve the desired template format:

        1. **Generate a Summary Heading**: Examine the input content to identify a all learning outcomes from core topic heading . Use this insight to create a dynamic heading for the summary section. This heading should reflect the core heading of the summary.

        2. **Write a Summary**: Under the dynamic heading you've created, craft a concise summary about 100 words long, capturing the essence of the input content.

        3. **List Learning Outcomes**: Under the '## Learning Outcomes' section, enumerate the learning outcomes provided, each with a one-line explanation derived from the core themes of the input content. You can find learning outcome from Core Theme heading in content

        4. **Map Learning Outcomes to Questions**: In the '## Mapping of LO's to Questions' section, create a clear mapping of Learning Outcomes to their corresponding question numbers, following the provided template structure.

        5. **Organize Multiple Choice Questions and Answers**: List out the MCQs under the '## Multiple Choice Questions and Answers' section as they appear in the content, including each question followed by its options (A, B, C, D) and the correct answer as per Map Learning Outcomes to Questions.

    Ensure all details are accurately extracted and formatted according to the guidelines. The number and specifics of questions and learning outcomes might vary, but the arrangement should adhere to the template structure.

    Given content for transformation should be analyzed for a summary heading, followed by sections for learning outcomes, mapping these outcomes to questions, and a series of multiple-choice questions with answers, according to the outline template below:

            # <Dynamic Summary Heading Extracted from Content>

            <Your 100-word summary here>

            ## Learning Outcomes

            1. **Learning Outcome 1**: <One-line explanation>
            2. **Learning Outcome 2**: <One-line explanation>
            N. **Learning Outcome N**: <One-line explanation>

            ## Mapping of LO's to Questions

            | Learning Outcome | Corresponding Question Numbers |
            |------------------|--------------------------------|
            | Learning Outcome 1 | 1, 2, 3 |
            | Learning Outcome 2 | 4, 5, 6 |
            ...
            | Learning Outcome N | N1, N2, N3 |

            ## Multiple Choice Questions and Answers

            **1. Question?**
            A) Option 1
            B) Option 2
            C) Option 3
            D) Option 4
            **Answer: B)**

            **2. Question?**
            A) Option 1
            B) Option 2
            C) Option 3
            D) Option 4
            **Answer: A)**

            **N. Question?**
            A) Option 1
            B) Option 2
            C) Option 3
            D) Option 4
            **Answer: D)**

        Example output:  
                        {output_quetions_format}

    Check the mapping table and ensure the number of questions matches before giving the output.
        
        """
    user_message = f"create a markdown file using the provided content. The sections marked by triple hashtags (###), as these indicate the content that needs to be organized.###{Content}###"
    response = client.chat.completions.create(
        model="gpt-4-turbo-preview",
        messages=[
            {"role": "system", "content": system_message.strip()},
            {"role": "user", "content": user_message.strip()}
        ],
        temperature=0
    )
    
    summary = response.choices[0].message.content
    logging.info(50*"#ouput#")
    logging.info(summary)
    file_path="quiz.md"
     # Writing the final string to the quiz.md file
    with open(file_path, 'w') as file:
        file.write(summary)



def graph(learning_outcomes,graphtitle="Visualizing Learning Outcome Similarities"):
    # Generate embeddings using OpenAI (assuming get_embedding is defined elsewhere)
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Generate embeddings
    embeddings = model.encode(learning_outcomes)

    # Compute cosine similarity
    cos_sim_matrix = cosine_similarity(embeddings)

    # Create a graph
    G = nx.Graph()

    # Add nodes with labels
    for idx, outcome in enumerate(learning_outcomes):
        G.add_node(idx, label=outcome)

    # Add edges based on cosine similarity
    threshold = 0.8  # Control edge creation based on similarity threshold
    for i in range(len(cos_sim_matrix)):
        for j in range(i + 1, len(cos_sim_matrix)):
            if cos_sim_matrix[i][j] > threshold:
                G.add_edge(i, j, weight=cos_sim_matrix[i][j])

    # Position nodes using the spring layout
    pos = nx.spring_layout(G)

    # Edge traces
    edge_trace = go.Scatter(
        x=[],
        y=[],
        line=dict(width=0.5, color='#888'),
        hoverinfo='none',
        mode='lines')

    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_trace['x'] += tuple([x0, x1, None])
        edge_trace['y'] += tuple([y0, y1, None])

    # Node traces
    node_trace = go.Scatter(
        x=[],
        y=[],
        text=[],
        mode='markers',
        hoverinfo='text',
        marker=dict(
            showscale=True,
            colorscale='YlGnBu',
            size=10,
            color=[],
            colorbar=dict(
                thickness=15,
                title='Node Connections',
                xanchor='left',
                titleside='right'
            ),
            line=dict(width=2)))

    for node in G.nodes():
        x, y = pos[node]
        node_trace['x'] += tuple([x])
        node_trace['y'] += tuple([y])
        node_trace['text'] += tuple([G.nodes[node]['label']])
        node_trace['marker']['color'] += tuple([len(G.edges(node))])

    # Create figure
    fig = go.Figure(data=[edge_trace, node_trace],
                    layout=go.Layout(
                        title=graphtitle,  # Add your title here
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=0, l=0, r=0, t=40),  # Adjust top margin to fit title
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False))
                    )

    fig.show()
from sklearn.cluster import KMeans
def filter_learning_outcomes(documents,num_clusters=5):
    api_key = os.getenv('OPENAI_API_KEY')
    client = openai.OpenAI(api_key=api_key)
    # Load a pre-trained Sentence Transformer model
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Generate embeddings for each document
    embeddings = model.encode(documents)

    # Apply k-means clustering
    kmeans = KMeans(n_clusters=num_clusters, random_state=42)
    kmeans.fit(embeddings)

    # Get the cluster labels
    labels = kmeans.labels_

    # Creating a dictionary to store clusters and their learning outcomes
    clusters = {}
    for i in range(num_clusters):
        clusters[f"Cluster {i+1}"] = []

    # Assigning learning outcomes to their respective clusters
    for idx, label in enumerate(labels):
        cluster_name = f"Cluster {label + 1}"
        clusters[cluster_name].append(documents[idx])
    logging.info(clusters)
    system_message = f"""
###As a professor specializing in the creation of learning outcomes, you are tasked with analyzing a dictionary where each key corresponds to a cluster of topics, and each value lists detailed learning outcomes for that cluster. 

###Your objectives are:

1.Identify the overarching theme or common objective within each cluster's learning outcomes.
2.Summarize the diverse topics within each cluster into a cohesive and informative statement that captures the essence of the educational goals, ensuring that even if topics differ, they are represented under the unified theme of the cluster.
3.Craft each summary to be distinct and specifically tailored to its cluster, steering clear of generic descriptions.
4.Compile these summaries into a Python list, with each entry corresponding to a particular cluster, ensuring the number of elements in the list matches the number of clusters in the input dictionary.
5.Dont add anything new to summary make sure everting is from provided cluster list

###Output:

Return a Python list containing the summarized learning outcomes. Each element of the list should correspond to a cluster, tailored to reflect the comprehensive educational goals of that cluster, inclusive of all topics, regardless of their diversity within the same cluster.
"""
    user_message = f"""
                        \"\"\"
                            Given an input dictionary of groups of learning outcomes, please summarize the list of learning outcomes for each cluster. The desired output is a Python list that covers all topics provided for each cluster's learning outcomes. Use the enclosed cluster dictionary provided between triple backticks:
```
{clusters} ```

Ensure that each element in the Python list reflects a comprehensive summary of the learning outcomes for each cluster, incorporating all associated topics
                        \"\"\"
                        """
    response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_message.strip()},
                {"role": "user", "content": user_message.strip()}
            ],
            temperature=0
        )
        
    summary = response.choices[0].message.content
    logging.info(summary)
    start = summary.find("[")
    end = summary.rfind("]") + 1
    outcome_list = eval(summary[start:end])


    return outcome_list
# Main execution
if __name__ == "__main__":
    remove_old_database_files()
    # Load environment variables from the .env file
    load_dotenv()

    # Define the path of the directory to analyze
    directory_path = r"C:\Users\dsksr\Documents\BIG DATA\2024\Independent Study\QIT-LC\Test"

    # Retrieve the OpenAI API key from environment variables
    api_key = os.getenv('OPENAI_API_KEY')
     # Retrieve the OpenAI API key from environment variables
    context_window_size =int(os.getenv('context_window_size'))
    encoding = tiktoken.encoding_for_model("gpt-4")
    persist_directory = 'docs/chroma/'
    try:
        # Analyze the directory and get details of the files present
        file_details = analyze_directory(directory_path)
        # Retrieve the contents of each file from the analyzed directory
        file_contents = get_file_contents(file_details)
        # Process and insert the file contents into the database
        vectordb = process_and_insert_contents(file_contents, persist_directory)
        # Summarize the content of the files using the OpenAI API
        summarized_contents = summarize_files(file_contents)
        chunked_contents = create_chunks_from_content_greedy(summarized_contents,context_window_size)
        list_of_learning_outcomes = generate_learning_outcomes_for_chunks(chunked_contents)
        logging.info(list_of_learning_outcomes)
        filtered_learning_outcomes = filter_learning_outcomes(list_of_learning_outcomes)
        logging.info(filtered_learning_outcomes)
        # graph(filtered_learning_outcomes[0],"Before Filter")
        # graph(filtered_learning_outcomes[1],"After Filter")

        #random_5_lo = random.sample(filtered_learning_outcomes, 5)
        #learning_outcomes_with_docs=find_most_relevant_learning_outcome_document(vectordb,random_5_lo)
        #Quetions = format_learning_outcomes_with_identifiers(learning_outcomes_with_docs)
        #logging.info(Quetions)
        #  mark_down = generate_markdown_file(Quetions)
        

    except Exception as e:
        logging.exception(f"An error occurred during execution: {e}")