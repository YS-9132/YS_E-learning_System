"""
E-ラーニングシステム用メール通知モジュール
クイズ完了時の結果通知・管理者への報告
"""

import smtplib
import yaml
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class EmailNotifier:
    """メール送信クラス"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Args:
            config_path: 設定ファイルのパス
        """
        self.config = self._load_config(config_path)
        self.smtp_server = self.config.get("email", {}).get("smtp_server", "smtp.gmail.com")
        self.smtp_port = self.config.get("email", {}).get("smtp_port", 587)
        self.sender_email = self.config.get("email", {}).get("sender_email", "")
        self.sender_password = self.config.get("email", {}).get("sender_password", "")
        self.admin_emails = self.config.get("email", {}).get("admin_emails", [])
        self.mail_enabled = self.config.get("email", {}).get("enabled", False)
    
    def _load_config(self, config_path: str) -> Dict:
        """YAML設定ファイルを読み込む"""
        try:
            if Path(config_path).exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"警告: 設定ファイルの読み込みに失敗しました: {e}")
        return {}
    
    def send_quiz_completion_email(self, user_name: str, user_email: str,
                                    course_name: str, score_percent: float,
                                    total_score: int, max_score: int,
                                    passed: bool) -> bool:
        """クイズ完了時のメールを送信（ユーザーへ）"""
        if not self.mail_enabled:
            print("メール通知は無効に設定されています")
            return False
        
        subject = f"【{course_name}】クイズ完了のお知らせ"
        
        html_body = self._generate_completion_email_html(
            user_name, course_name, score_percent, total_score, max_score, passed
        )
        
        return self._send_email(user_email, subject, html_body)
    
    def send_admin_notification(self, user_name: str, user_email: str,
                               course_name: str, score_percent: float,
                               total_score: int, max_score: int,
                               passed: bool) -> bool:
        """クイズ完了時のメールを送信（管理者へ）"""
        if not self.mail_enabled or not self.admin_emails:
            print("管理者メール通知は無効に設定されています")
            return False
        
        subject = f"【管理者報告】{user_name}が{course_name}を完了しました"
        
        html_body = self._generate_admin_notification_html(
            user_name, user_email, course_name, score_percent, total_score, max_score, passed
        )
        
        success = True
        for admin_email in self.admin_emails:
            if not self._send_email(admin_email, subject, html_body):
                success = False
        
        return success
    
    def _generate_completion_email_html(self, user_name: str, course_name: str,
                                        score_percent: float, total_score: int,
                                        max_score: int, passed: bool) -> str:
        """ユーザー向けメールのHTML生成"""
        status = "✅ 合格" if passed else "❌ 不合格"
        status_color = "#28a745" if passed else "#dc3545"
        
        html = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Arial', sans-serif; margin: 0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; }}
                .content {{ padding: 20px; }}
                .score-box {{ 
                    background-color: {status_color}; 
                    color: white; 
                    padding: 15px; 
                    border-radius: 5px; 
                    text-align: center; 
                    margin: 20px 0;
                }}
                .score-value {{ font-size: 32px; font-weight: bold; }}
                .footer {{ background-color: #f8f9fa; padding: 15px; text-align: center; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
                .label {{ font-weight: bold; background-color: #f0f0f0; width: 40%; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>{user_name}さんへ</h2>
                    <p>クイズ完了のお知らせです。</p>
                </div>
                
                <div class="content">
                    <h3>【{course_name}】クイズ結果</h3>
                    
                    <div class="score-box">
                        <div style="font-size: 18px; margin-bottom: 10px;">判定</div>
                        <div class="score-value">{status}</div>
                    </div>
                    
                    <table>
                        <tr>
                            <td class="label">取得点数</td>
                            <td>{total_score} / {max_score}点</td>
                        </tr>
                        <tr>
                            <td class="label">正答率</td>
                            <td>{score_percent:.1f}%</td>
                        </tr>
                        <tr>
                            <td class="label">完了日時</td>
                            <td>{datetime.now().strftime('%Y年%m月%d日 %H:%M')}</td>
                        </tr>
                    </table>
                    
                    <p>ご不明な点がございましたら、お気軽にお問い合わせください。</p>
                </div>
                
                <div class="footer">
                    <p>このメールに心当たりがない場合は、破棄してください。</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html
    
    def _generate_admin_notification_html(self, user_name: str, user_email: str,
                                          course_name: str, score_percent: float,
                                          total_score: int, max_score: int,
                                          passed: bool) -> str:
        """管理者向けメールのHTML生成"""
        status = "合格" if passed else "不合格"
        
        html = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Arial', sans-serif; margin: 0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .header {{ background-color: #003366; color: white; padding: 20px; border-radius: 5px; }}
                .content {{ padding: 20px; }}
                .info-box {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .footer {{ background-color: #f8f9fa; padding: 15px; text-align: center; color: #666; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
                .label {{ font-weight: bold; background-color: #e0e0e0; width: 30%; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>【管理者報告】クイズ完了通知</h2>
                </div>
                
                <div class="content">
                    <div class="info-box">
                        <p><strong>ユーザー:</strong> {user_name} ({user_email})</p>
                        <p><strong>コース:</strong> {course_name}</p>
                        <p><strong>完了日時:</strong> {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
                    </div>
                    
                    <h3>成績</h3>
                    <table>
                        <tr>
                            <td class="label">判定</td>
                            <td><strong>{status}</strong></td>
                        </tr>
                        <tr>
                            <td class="label">得点</td>
                            <td>{total_score} / {max_score}点</td>
                        </tr>
                        <tr>
                            <td class="label">正答率</td>
                            <td>{score_percent:.1f}%</td>
                        </tr>
                    </table>
                    
                    <p>詳細はシステム管理画面をご参照ください。</p>
                </div>
                
                <div class="footer">
                    <p>このメールは自動送信です。</p>
                </div>
            </div>
        </body>
        </html>
        """
        return html
    
    def _send_email(self, recipient_email: str, subject: str, html_body: str) -> bool:
        """メール送信の実行"""
        try:
            if not self.sender_email or not self.sender_password:
                print("エラー: メール送信の認証情報が設定されていません")
                return False
            
            # メッセージを構成
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = recipient_email
            
            # HTMLを添付
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            
            # メール送信
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            
            print(f"✅ メール送信成功: {recipient_email}")
            return True
        
        except smtplib.SMTPAuthenticationError:
            print("エラー: メール認証に失敗しました（ユーザー名またはパスワードが正しくない）")
            return False
        except smtplib.SMTPException as e:
            print(f"エラー: SMTP通信エラー: {e}")
            return False
        except Exception as e:
            print(f"エラー: メール送信に失敗しました: {e}")
            return False
