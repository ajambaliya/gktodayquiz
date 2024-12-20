import os
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from telegram import Bot, Poll
import asyncio
import time
import re
from pymongo import MongoClient

print(f"BOT_TOKEN: {'Set' if os.getenv('BOT_TOKEN') else 'Not set'}")
print(f"TELEGRAM_CHANNEL_USERNAME: {os.getenv('TELEGRAM_CHANNEL_USERNAME')}")
print(f"MONGO_CONNECTION_STRING: {'Set' if os.getenv('MONGO_CONNECTION_STRING') else 'Not set'}")

# Load environment variables
DB_NAME = 'indiabixurl'
COLLECTION_NAME = 'ScrapedLinks'
MONGO_CONNECTION_STRING = os.getenv('MONGO_CONNECTION_STRING')
BOT_TOKEN = os.getenv('BOT_TOKEN')
TELEGRAM_CHANNEL_USERNAME = os.getenv('TELEGRAM_CHANNEL_USERNAME')

# Connect to MongoDB
def get_mongo_client():
    client = MongoClient(MONGO_CONNECTION_STRING)
    return client[DB_NAME][COLLECTION_NAME]

def get_stored_urls(collection):
    return set(doc['url'] for doc in collection.find({"url": {"$exists": True}}))

def store_url(collection, url):
    collection.update_one({'url': url}, {'$set': {'url': url}}, upsert=True)

# Function to fetch links from a URL
def fetch_links(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    div = soup.find('div', class_='inside_post column content_width')
    links = div.find_all('a', href=True)
    return {i+1: link['href'] for i, link in enumerate(links)}

# Function to scrape content from the selected links
def scrape_content_from_links(selected_links):
    all_questions = []
    for link in selected_links:
        response = requests.get(link)
        soup = BeautifulSoup(response.text, 'html.parser')
        post_content = soup.find('div', class_='inside_post column content_width')
        if post_content:
            questions = extract_questions(post_content)
            all_questions.extend(questions)
    return all_questions

# Function to extract questions, options, and correct answers
def extract_questions(post_content):
    questions = []
    quiz_questions = post_content.find_all('div', class_='wp_quiz_question testclass')
    for quiz in quiz_questions:
        question_text = quiz.text.strip()
        options_div = quiz.find_next('div', class_='wp_quiz_question_options')
        options_raw = options_div.get_text(separator='\n').split('\n')
        
        # Clean and process options
        options = []
        for opt in options_raw:
            clean_option = re.sub(r'^\s*\[.\]\s*', '', opt).strip()
            if clean_option:
                options.append(clean_option)
        
        # Try the first method to find the correct answer
        answer_div = quiz.find_next('div', class_='wp_basic_quiz_answer')
        correct_answer_text = answer_div.find('div', class_='ques_answer').text.strip()
        correct_answer_letter = correct_answer_text.split(':')[-1].strip()[0]  # Should be 'A', 'B', 'C', or 'D'

        # Ensure correct_answer_letter is a valid option
        if correct_answer_letter not in ['A', 'B', 'C', 'D']:
            print(f"Warning: Unexpected correct answer letter '{correct_answer_letter}' for question: {question_text}")
            correct_answer_index = -1  # Could use -1 to indicate missing/invalid answer
        else:
            correct_answer_index = ['A', 'B', 'C', 'D'].index(correct_answer_letter)
        
        # If the first method fails, try the second method
        if correct_answer_index == -1:
            correct_answer_index = find_correct_answer_second_method(quiz)
        
        if len(options) >= 2 and correct_answer_index != -1:
            questions.append({
                'question': question_text,
                'options': options,
                'correct_answer': correct_answer_index
            })
    return questions


def find_correct_answer_second_method(quiz):
    try:
        correct_answer_div = quiz.find('div', class_='correct_answer')
        correct_answer_letter = correct_answer_div.text.strip()[0]
        correct_answer_index = ['A', 'B', 'C', 'D'].index(correct_answer_letter)
        return correct_answer_index
    except:
        return -1  # Return -1 if the second method also fails

# Function to translate text to Gujarati
def translate_text(text, target_language='gu'):
    translator = GoogleTranslator(source='auto', target=target_language)
    translated_text = translator.translate(text)
    return translated_text

# Function to send questions as polls to the Telegram channel
async def send_polls(questions):
    bot = Bot(token=BOT_TOKEN)
    for q in questions:
        question = q['question']
        options = q['options']
        
        # Translate the question and options
        translated_question = translate_text(question)
        translated_options = [translate_text(opt) for opt in options]
        
        # Translate the correct answer index
        correct_option_id = q['correct_answer']
        
        try:
            await bot.send_poll(
                chat_id=TELEGRAM_CHANNEL_USERNAME,
                question=translated_question,
                options=translated_options,
                type=Poll.QUIZ,
                correct_option_id=correct_option_id,
                is_anonymous=True
            )
        except Exception as e:
            print(f"Error sending poll: {e}")
            print(f"TELEGRAM_CHANNEL_USERNAME: {TELEGRAM_CHANNEL_USERNAME}")
        time.sleep(3)  # Adding a 3-second delay between sending polls

def main():
    url = "https://www.gktoday.in/gk-current-affairs-quiz-questions-answers/"
    links = fetch_links(url)

    # Connect to MongoDB and get stored URLs
    collection = get_mongo_client()
    stored_urls = get_stored_urls(collection)

    # Filter new links
    new_links = {num: link for num, link in links.items() if link not in stored_urls}
    
    if not new_links:
        print("No new links to scrape.")
        return

    # Process all new links
    for link in new_links.values():
        print(f"Scraping link: {link}")
        questions = scrape_content_from_links([link])
        if questions:
            asyncio.run(send_polls(questions))
            # Store new URL in MongoDB
            store_url(collection, link)
        else:
            print(f"No questions found on {link}.")

if __name__ == "__main__":
    main()
