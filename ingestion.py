import asyncio
import io
import json
import os
import requests

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from blob import upload_matches_zip, read_file

# Load environment variables
load_dotenv()

DB_HOST = os.environ['HOSTNAME']
DB_NAME = os.environ['DATABASE']
DB_USER = os.environ['USER']
DB_PASSWORD = os.environ['PASSWORD']
MATCHES_DIR = 'data/matches/'

class DatabaseManager:
    """Handles all database-related operations."""
    def __init__(self, user, password, host, dbname):
        self.engine = create_async_engine(f"postgresql+asyncpg://{user}:{password}@{host}/{dbname}")
        self.Session = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.execute(text('''
                CREATE TABLE IF NOT EXISTS raw_match_info (
                    match_id INTEGER PRIMARY KEY,
                    match_data JSONB,
                    deliveries JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            await conn.commit()

    @asynccontextmanager
    async def async_session_scope(self):        
        async with self.Session() as session:
            try:
                yield session
                await session.commit()
            except:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def insert_file_data(self, json_path):
        match_data = await read_file(json_path)
        match_id = os.path.basename(json_path).split('.')[0]

        print(f"Processing match {match_id}")
        try:
            async with self.async_session_scope() as session:
                await session.execute(text('''
                    INSERT INTO raw_match_info (match_id, match_data, deliveries)
                    VALUES (:match_id, :match_data, :deliveries)
                '''),
                {'match_id': int(match_id), 'match_data': json.dumps(match_data['info']), 'deliveries': json.dumps(match_data['innings'])})
        except IntegrityError:
            print(f"Match with ID {match_id} already exists in the database.")
            return

class MatchDataManager:
    """Handles downloading and loading match data files."""
    def __init__(self, db_manager, matches_dir=MATCHES_DIR):
        self.db_manager = db_manager
        self.matches_dir = matches_dir

    def download_and_extract_matches(self, matches_url):
        response = requests.get(matches_url)
        zip_file = io.BytesIO(response.content)
        uploaded_file_urls = upload_matches_zip(zip_file)
        return uploaded_file_urls

    async def load_files_to_db(self, file_urls):
        tasks = [self.db_manager.insert_file_data(file_url) for file_url in file_urls]
        await asyncio.gather(*tasks)

async def main(url):
    if url:
        db_manager = DatabaseManager(DB_USER, DB_PASSWORD, DB_HOST, DB_NAME)
        await db_manager.init_db()  # Ensure the database is initialized
        match_data_manager = MatchDataManager(db_manager)

        # Download matches and process data
        file_urls = match_data_manager.download_and_extract_matches(url)
        await match_data_manager.load_files_to_db(file_urls)

        return {
            'statusCode': 200,
            'body': 'Matches downloaded and data loaded successfully.'
        }
    else:
        return {
            'statusCode': 400,
            'body': 'URL not provided.'
        }

if __name__ == "__main__":
    url = "https://cricsheet.org/downloads/recently_played_2_male_json.zip"
    asyncio.run(main(url))