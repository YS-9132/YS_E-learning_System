"""
E-ラーニングシステム用データベース管理モジュール
ユーザー管理・回答履歴・得点保存
"""

import sqlite3
import hashlib
import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


class DatabaseManager:
    """SQLiteデータベース管理クラス"""
    
    def __init__(self, db_path: str = "elearning.db"):
        """
        Args:
            db_path: データベースファイルのパス
        """
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """データベース接続を取得"""
        return sqlite3.connect(self.db_path)
    
    def init_database(self):
        """データベーステーブルを初期化"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ユーザーテーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                full_name TEXT,
                role TEXT DEFAULT 'student',
                status TEXT DEFAULT 'active',
                failed_login_count INTEGER DEFAULT 0,
                locked_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # コース情報テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS courses (
                course_id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name TEXT UNIQUE NOT NULL,
                description TEXT,
                pdf_path TEXT,
                pptx_path TEXT,
                access_start_date TEXT,
                access_end_date TEXT,
                quiz_time_limit_seconds INTEGER DEFAULT 300,
                passing_score_percent INTEGER DEFAULT 70,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 回答履歴テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                selected_answers TEXT,
                is_correct BOOLEAN,
                score_earned INTEGER,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (course_id) REFERENCES courses(course_id)
            )
        ''')
        
        # コース成績テーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS course_scores (
                score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                total_score INTEGER,
                max_score INTEGER,
                score_percent REAL,
                passed BOOLEAN,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, course_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (course_id) REFERENCES courses(course_id)
            )
        ''')
        
        # 通知ログテーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_id INTEGER,
                notification_type TEXT,
                recipient_email TEXT,
                status TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (course_id) REFERENCES courses(course_id)
            )
        ''')
        
        # ログイン試行ログテーブル
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT,
                ip_address TEXT,
                user_agent TEXT,
                error_message TEXT,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # ===== コース管理 =====
        """パスワードをハッシュ化"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def add_user(self, username: str, password: str, email: str = "", 
                 full_name: str = "", role: str = "student") -> bool:
        """新規ユーザーを追加"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            password_hash = self.hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, password_hash, email, full_name, role)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, password_hash, email, full_name, role))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def authenticate_user(self, username: str, password: str, 
                          ip_address: str = "", user_agent: str = "") -> Optional[Dict]:
        """
        ユーザー認証（詳細なチェック付き）
        
        Returns:
            成功時: {"user_id": id, "status": "success"}
            失敗時: {"status": "failed", "message": "エラーメッセージ"}
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ユーザーを検索
        cursor.execute('''
            SELECT user_id, password_hash, status, failed_login_count, locked_until
            FROM users WHERE username = ?
        ''', (username,))
        
        result = cursor.fetchone()
        
        # ユーザーが存在しない
        if not result:
            self._log_login_attempt(None, username, "failed", ip_address, user_agent, 
                                   "ユーザーが見つかりません")
            conn.close()
            return {
                "status": "failed",
                "message": "ユーザー名またはパスワードが正しくありません"
            }
        
        user_id, password_hash, status, failed_count, locked_until = result
        
        # チェック1: ユーザーが無効・停止中
        if status != 'active':
            self._log_login_attempt(user_id, username, "failed", ip_address, user_agent,
                                   f"ユーザーステータス: {status}")
            conn.close()
            return {
                "status": "failed",
                "message": f"このアカウントは {status} です。管理者に連絡してください。"
            }
        
        # チェック2: ロックアウト中
        if locked_until:
            locked_until_dt = datetime.fromisoformat(locked_until)
            if datetime.now() < locked_until_dt:
                remaining_minutes = int((locked_until_dt - datetime.now()).total_seconds() / 60)
                self._log_login_attempt(user_id, username, "failed", ip_address, user_agent,
                                       f"アカウントロック中（残り{remaining_minutes}分）")
                conn.close()
                return {
                    "status": "failed",
                    "message": f"アカウントがロックされています。{remaining_minutes}分後に再度お試しください。"
                }
            else:
                # ロック期間が終了したのでリセット
                cursor.execute('''
                    UPDATE users SET failed_login_count = 0, locked_until = NULL
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
                failed_count = 0
        
        # チェック3: パスワードが正しい
        provided_hash = self.hash_password(password)
        if password_hash != provided_hash:
            # ログイン失敗カウントをインクリメント
            new_failed_count = failed_count + 1
            
            # 設定から失敗上限と ロックアウト時間を読み込む
            config = self._load_config()
            max_attempts = config.get('users', {}).get('max_login_attempts', 5)
            lockout_minutes = config.get('users', {}).get('lockout_minutes', 30)
            
            # 失敗回数が上限を超えたらロック
            if new_failed_count >= max_attempts:
                locked_until = datetime.now() + timedelta(minutes=lockout_minutes)
                cursor.execute('''
                    UPDATE users 
                    SET failed_login_count = ?, locked_until = ?
                    WHERE user_id = ?
                ''', (new_failed_count, locked_until, user_id))
                self._log_login_attempt(user_id, username, "failed", ip_address, user_agent,
                                       f"パスワード不一致 - ロック中（{lockout_minutes}分）")
                conn.commit()
                conn.close()
                return {
                    "status": "failed",
                    "message": f"パスワードが正しくありません。{max_attempts}回失敗したため、アカウントが{lockout_minutes}分間ロックされました。"
                }
            else:
                # まだロックされない
                cursor.execute('''
                    UPDATE users SET failed_login_count = ? WHERE user_id = ?
                ''', (new_failed_count, user_id))
                remaining_attempts = max_attempts - new_failed_count
                self._log_login_attempt(user_id, username, "failed", ip_address, user_agent,
                                       f"パスワード不一致（残り{remaining_attempts}回）")
                conn.commit()
                conn.close()
                return {
                    "status": "failed",
                    "message": f"パスワードが正しくありません。残り {remaining_attempts} 回試行できます。"
                }
        
        # ログイン成功！
        cursor.execute('''
            UPDATE users 
            SET last_login = ?, failed_login_count = 0, locked_until = NULL
            WHERE user_id = ?
        ''', (datetime.now(), user_id))
        
        self._log_login_attempt(user_id, username, "success", ip_address, user_agent, None)
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "user_id": user_id
        }
    
    def _load_config(self) -> Dict:
        """設定ファイルを読み込む"""
        try:
            if Path("config.yaml").exists():
                with open("config.yaml", 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
        except:
            pass
        return {}
    
    def get_user_info(self, user_id: int) -> Optional[Dict]:
        """ユーザー情報を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email, full_name, role, status, created_at, last_login
            FROM users WHERE user_id = ?
        ''', (user_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "user_id": result[0],
                "username": result[1],
                "email": result[2],
                "full_name": result[3],
                "role": result[4],
                "status": result[5],
                "created_at": result[6],
                "last_login": result[7]
            }
        return None
    
    # ===== コース管理 =====
    
    def add_course(self, course_name: str, description: str = "", 
                   pdf_path: str = "", pptx_path: str = "",
                   access_start_date: str = "", access_end_date: str = "",
                   quiz_time_limit: int = 300, passing_score: int = 70) -> bool:
        """新規コースを追加"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO courses 
                (course_name, description, pdf_path, pptx_path, 
                 access_start_date, access_end_date, quiz_time_limit_seconds, passing_score_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (course_name, description, pdf_path, pptx_path,
                  access_start_date, access_end_date, quiz_time_limit, passing_score))
            conn.commit()
            course_id = cursor.lastrowid
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_courses(self) -> List[Dict]:
        """すべてのコースを取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT course_id, course_name, description, quiz_time_limit_seconds,
                   passing_score_percent, created_at
            FROM courses ORDER BY created_at DESC
        ''')
        
        courses = []
        for row in cursor.fetchall():
            courses.append({
                "course_id": row[0],
                "course_name": row[1],
                "description": row[2],
                "quiz_time_limit": row[3],
                "passing_score": row[4],
                "created_at": row[5]
            })
        
        conn.close()
        return courses
    
    # ===== 採点・結果管理 =====
    
    def save_quiz_result(self, user_id: int, course_id: int, question_id: int,
                         selected_answers: List[str], is_correct: bool, 
                         score_earned: int) -> bool:
        """クイズの回答結果を保存"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            answers_json = json.dumps(selected_answers, ensure_ascii=False)
            cursor.execute('''
                INSERT INTO quiz_results 
                (user_id, course_id, question_id, selected_answers, is_correct, score_earned)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, course_id, question_id, answers_json, is_correct, score_earned))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"エラー: 結果の保存に失敗しました: {e}")
            return False
    
    def save_course_score(self, user_id: int, course_id: int, 
                          total_score: int, max_score: int,
                          passing_score_percent: int) -> Dict:
        """コースの最終得点を保存"""
        score_percent = (total_score / max_score * 100) if max_score > 0 else 0
        passed = score_percent >= passing_score_percent
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 既存の記録があれば更新、なければ挿入
            cursor.execute('''
                INSERT OR REPLACE INTO course_scores
                (user_id, course_id, total_score, max_score, score_percent, passed, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, course_id, total_score, max_score, score_percent, passed, datetime.now()))
            
            conn.commit()
            conn.close()
            
            return {
                "total_score": total_score,
                "max_score": max_score,
                "score_percent": round(score_percent, 2),
                "passed": passed
            }
        except Exception as e:
            print(f"エラー: 成績の保存に失敗しました: {e}")
            return {}
    
    def get_user_course_score(self, user_id: int, course_id: int) -> Optional[Dict]:
        """ユーザーのコース成績を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT total_score, max_score, score_percent, passed, completed_at
            FROM course_scores
            WHERE user_id = ? AND course_id = ?
        ''', (user_id, course_id))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "total_score": result[0],
                "max_score": result[1],
                "score_percent": result[2],
                "passed": result[3],
                "completed_at": result[4]
            }
        return None
    
    def get_user_quiz_history(self, user_id: int, course_id: int) -> List[Dict]:
        """ユーザーのクイズ回答履歴を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT question_id, selected_answers, is_correct, score_earned, attempted_at
            FROM quiz_results
            WHERE user_id = ? AND course_id = ?
            ORDER BY attempted_at DESC
        ''', (user_id, course_id))
        
        history = []
        for row in cursor.fetchall():
            history.append({
                "question_id": row[0],
                "selected_answers": json.loads(row[1]),
                "is_correct": row[2],
                "score_earned": row[3],
                "attempted_at": row[4]
            })
        
        conn.close()
        return history
    
    def log_notification(self, user_id: int, course_id: int, 
                         notification_type: str, recipient_email: str, 
                         status: str = "sent") -> bool:
        """通知ログを記録"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notification_logs
                (user_id, course_id, notification_type, recipient_email, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, course_id, notification_type, recipient_email, status))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"エラー: 通知ログの記録に失敗しました: {e}")
            return False
    
    def get_admin_statistics(self) -> Dict:
        """管理者向け統計情報を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ユーザー数
        cursor.execute('SELECT COUNT(*) FROM users WHERE role = "student"')
        total_users = cursor.fetchone()[0]
        
        # コース数
        cursor.execute('SELECT COUNT(*) FROM courses')
        total_courses = cursor.fetchone()[0]
        
        # 完了者数
        cursor.execute('SELECT COUNT(*) FROM course_scores WHERE passed = 1')
        completed_users = cursor.fetchone()[0]
        
        # 平均スコア
        cursor.execute('SELECT AVG(score_percent) FROM course_scores')
        avg_score = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_users": total_users,
            "total_courses": total_courses,
            "completed_users": completed_users,
            "average_score": round(avg_score, 2)
        }
    
    # ===== ユーザーステータス管理 =====
    
    def update_user_status(self, user_id: int, status: str) -> bool:
        """ユーザーステータスを更新（active/suspended/disabled）"""
        if status not in ['active', 'suspended', 'disabled']:
            return False
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET status = ? WHERE user_id = ?
            ''', (status, user_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"エラー: ステータス更新に失敗: {e}")
            return False
    
    def unlock_user(self, user_id: int) -> bool:
        """ユーザーのロックアウトを解除"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET failed_login_count = 0, locked_until = NULL
                WHERE user_id = ?
            ''', (user_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"エラー: ロック解除に失敗: {e}")
            return False
    
    def _log_login_attempt(self, user_id: Optional[int], username: str, 
                          status: str, ip_address: str = "", 
                          user_agent: str = "", error_message: str = None) -> bool:
        """ログイン試行をログテーブルに記録"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO login_logs 
                (user_id, username, status, ip_address, user_agent, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, status, ip_address, user_agent, error_message))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"エラー: ログイン試行ログの記録に失敗: {e}")
            return False
    
    def get_login_logs(self, user_id: int = None, limit: int = 50) -> List[Dict]:
        """ログイン試行ログを取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if user_id:
            cursor.execute('''
                SELECT log_id, user_id, username, status, ip_address, 
                       error_message, attempted_at
                FROM login_logs
                WHERE user_id = ?
                ORDER BY attempted_at DESC
                LIMIT ?
            ''', (user_id, limit))
        else:
            cursor.execute('''
                SELECT log_id, user_id, username, status, ip_address, 
                       error_message, attempted_at
                FROM login_logs
                ORDER BY attempted_at DESC
                LIMIT ?
            ''', (limit,))
        
        logs = []
        for row in cursor.fetchall():
            logs.append({
                "log_id": row[0],
                "user_id": row[1],
                "username": row[2],
                "status": row[3],
                "ip_address": row[4],
                "error_message": row[5],
                "attempted_at": row[6]
            })
        
        conn.close()
        return logs
    
    def get_all_users(self) -> List[Dict]:
        """すべてのユーザー情報を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, email, full_name, role, status, 
                   failed_login_count, last_login, created_at
            FROM users
            ORDER BY created_at DESC
        ''')
        
        users = []
        for row in cursor.fetchall():
            users.append({
                "user_id": row[0],
                "username": row[1],
                "email": row[2],
                "full_name": row[3],
                "role": row[4],
                "status": row[5],
                "failed_login_count": row[6],
                "last_login": row[7],
                "created_at": row[8]
            })
        
        conn.close()
        return users
