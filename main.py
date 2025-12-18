import requests
import json
import time
from datetime import datetime

class RefBot:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.example.com"  # Замени на реальный URL API
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
    def get_referrals(self):
        """Получить список рефералов"""
        try:
            response = requests.get(
                f"{self.base_url}/referrals",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при получении рефералов: {e}")
            return None
    
    def add_referral(self, user_id, referral_code):
        """Добавить нового реферала"""
        data = {
            "user_id": user_id,
            "referral_code": referral_code,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/referrals/add",
                headers=self.headers,
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при добавлении реферала: {e}")
            return None
    
    def check_rewards(self):
        """Проверить доступные награды"""
        try:
            response = requests.get(
                f"{self.base_url}/rewards",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при проверке наград: {e}")
            return None
    
    def claim_reward(self, reward_id):
        """Запросить награду"""
        data = {"reward_id": reward_id}
        
        try:
            response = requests.post(
                f"{self.base_url}/rewards/claim",
                headers=self.headers,
                json=data
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе награды: {e}")
            return None
    
    def generate_report(self):
        """Сгенерировать отчет по рефералам"""
        referrals = self.get_referrals()
        if not referrals:
            return None
            
        report = {
            "total_referrals": len(referrals),
            "active_referrals": sum(1 for r in referrals if r.get("active", False)),
            "total_rewards": self.check_rewards() or [],
            "generated_at": datetime.now().isoformat()
        }
        
        return report
    
    def run_continuously(self, interval=60):
        """Запустить бота в непрерывном режиме"""
        print("Реф бот запущен...")
        while True:
            try:
                # Проверка новых рефералов
                referrals = self.get_referrals()
                if referrals:
                    print(f"Найдено рефералов: {len(referrals)}")
                
                # Проверка наград
                rewards = self.check_rewards()
                if rewards:
                    print(f"Доступно наград: {len(rewards)}")
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                print("\nБот остановлен")
                break
            except Exception as e:
                print(f"Ошибка в основном цикле: {e}")
                time.sleep(interval)

# Пример использования
if __name__ == "__main__":
    # Инициализация бота с API ключом
    bot = RefBot(api_key="8126450707:AAE1grJdi8DReGgCHJdE2MzEa7ocNVClvq8")
    
    # Получить рефералов
    referrals = bot.get_referrals()
    print(f"Рефералы: {referrals}")
    
    # Добавить нового реферала
    # bot.add_referral(user_id=123, referral_code="REF123")
    
    # Запустить в непрерывном режиме
    # bot.run_continuously(interval=300)  # Проверка каждые 5 минут
