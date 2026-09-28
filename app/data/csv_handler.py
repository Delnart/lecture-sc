import csv
from typing import List, Dict, Any, Optional

class CSVHandler:
    def __init__(self, file_path="app/data/faq_data.csv"):
        self.path = file_path
        self._content: List[Dict[int, Any]] = [] # [key: id -> question,answer]
        self._lookup: Dict[int, str] = {}
        self.load_data()
        
    def load_data(self) -> bool:
        try:
            with open(self.path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file, skipinitialspace=True)

                new_content = []
                new_lookup = {}
                for row in reader:
                    row['id'] = int(row['id'])
                    new_content.append(row)
                    new_lookup[row['id']] = row['answer']

            self._content = new_content
            self._lookup = new_lookup
            return True
        except (FileNotFoundError, ValueError, KeyError) as e:
            return False
      
    def get_questions(self, force_reload: bool = False):
        if not self._content or force_reload:
            self.load_data()
        return self._content
      
    def get_answer_by_id(self, q_id: int) -> Optional[str]:
        if not self._lookup:
            self.load_data()
        return self._lookup.get(q_id)

    def add_questions(self, question:str, answer:str) -> bool:

        try:
            questions_list = self.get_questions()

            if questions_list:
                next_id = max(item['id'] for item in questions_list) + 1
            else:
                # якщо файл порожній, то індекс буде 1
                next_id = 1

            with open(self.path, mode='a', encoding='utf-8', newline='') as file:
                writer = csv.writer(file, quoting=csv.QUOTE_MINIMAL)
                writer.writerow([next_id, question, answer])

            self.load_data()
            return True
        except Exception as e:
            return False

    def update_question(self, q_id: int, question: str = None, answer: str = None) -> bool:
        try:
            self.load_data()
            found = False
            for item in self._content:
                if item.get("id") == q_id:
                    if question is not None:
                        item["question"] = question
                    if answer is not None:
                        item["answer"] = answer
                    found = True
                    break

            if not found:
                return False

            with open(self.path, mode="w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["id", "question", "answer"])
                writer.writeheader()
                for item in self._content:
                    writer.writerow(item)

            self.load_data()
            return True
        except Exception as e:
            return False
