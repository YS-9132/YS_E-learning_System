"""
E-ラーニングシステム メインアプリケーション
Microsoft Azure AD SSO統合版
Streamlit ベース
"""

import streamlit as st
import json
import yaml
import pandas as pd
import msal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# 自作モジュールのインポート
from ppt_extractor import PPTExtractor
from database_manager import DatabaseManager
from email_notifier import EmailNotifier


# ===== ページ設定 =====
st.set_page_config(
    page_title="E-ラーニングシステム",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== カスタムCSS =====
st.markdown("""
<style>
    .main-header {
        color: #003366;
        text-align: center;
        padding: 20px;
    }
    .score-box {
        background-color: #e8f4f8;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .status-passed {
        color: #28a745;
        font-weight: bold;
    }
    .status-failed {
        color: #dc3545;
        font-weight: bold;
    }
    .sso-login-btn {
        background-color: #0078d4;
        color: white;
        padding: 15px 30px;
        border-radius: 5px;
        border: none;
        font-size: 16px;
        cursor: pointer;
    }
</style>
""", unsafe_allow_html=True)


# ===== 初期化関数 =====

def load_config(config_path: str = "config.yaml") -> Dict:
    """設定ファイルを読み込む"""
    try:
        if Path(config_path).exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        else:
            st.error(f"設定ファイルが見つかりません: {config_path}")
            return {}
    except Exception as e:
        st.error(f"設定ファイルの読み込みエラー: {e}")
        return {}


def load_employees_csv(csv_path: str = "employees.csv") -> Dict:
    """社員マスターCSVを読み込む（メール → 社員番号のマッピング）"""
    try:
        if Path(csv_path).exists():
            df = pd.read_csv(csv_path)
            # メールアドレスをキーにしたマッピングを作成
            mapping = {}
            for _, row in df.iterrows():
                email = row['メールアドレス'].lower().strip()
                employee_id = str(row['社員番号']).strip() if pd.notna(row['社員番号']) and str(row['社員番号']).strip() else None
                full_name = row['フルネーム'].strip() if pd.notna(row['フルネーム']) else ""
                
                # 社員番号がない場合はメールアドレスをそのまま使用
                if not employee_id:
                    employee_id = email.split('@')[0]  # @の前の部分を使用
                
                mapping[email] = {
                    "employee_id": employee_id,
                    "full_name": full_name,
                    "email": email
                }
            
            return mapping
        else:
            st.warning(f"社員マスターが見つかりません: {csv_path}")
            return {}
    except Exception as e:
        st.error(f"社員マスターの読み込みエラー: {e}")
        return {}


def init_session_state():
    """セッション状態を初期化"""
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'employee_id' not in st.session_state:
        st.session_state.employee_id = None
    if 'full_name' not in st.session_state:
        st.session_state.full_name = None
    if 'email' not in st.session_state:
        st.session_state.email = None
    if 'role' not in st.session_state:
        st.session_state.role = None
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "login"
    if 'quiz_started' not in st.session_state:
        st.session_state.quiz_started = False
    if 'quiz_answers' not in st.session_state:
        st.session_state.quiz_answers = {}
    if 'quiz_start_time' not in st.session_state:
        st.session_state.quiz_start_time = None


# ===== Azure AD SSO認証 =====

def get_azure_ad_app(config: Dict) -> msal.PublicClientApplication:
    """Azure ADアプリケーションを初期化"""
    azure_config = config.get('azure_ad', {})
    
    app = msal.PublicClientApplication(
        client_id=azure_config['client_id'],
        authority=azure_config['authority']
    )
    return app


def authenticate_with_azure_ad(config: Dict, employees_mapping: Dict) -> Optional[Dict]:
    """Azure ADでユーザーを認証"""
    azure_config = config.get('azure_ad', {})
    app = get_azure_ad_app(config)
    
    try:
        # 対話的にトークンを取得
        result = app.acquire_token_interactive(scopes=azure_config['scopes'])
        
        if "access_token" in result:
            # ユーザー情報を取得
            user_info = {
                "name": result.get("name", ""),
                "email": result.get("unique_name", "").lower(),
                "id": result.get("oid", "")
            }
            
            # メールアドレスから社員情報を検索
            email = user_info['email']
            
            if email in employees_mapping:
                employee_info = employees_mapping[email]
                return {
                    "status": "success",
                    "email": email,
                    "full_name": employee_info['full_name'],
                    "employee_id": employee_info['employee_id'],
                    "azure_id": user_info['id']
                }
            else:
                return {
                    "status": "failed",
                    "message": f"メールアドレス '{email}' が社員マスターに見つかりません。\n管理者に連絡してください。"
                }
        else:
            error = result.get("error", "不明なエラー")
            return {
                "status": "failed",
                "message": f"Azure AD認証に失敗しました: {error}"
            }
    
    except Exception as e:
        return {
            "status": "failed",
            "message": f"認証エラー: {str(e)}"
        }


def load_questions(questions_file: str = "questions.json") -> List[Dict]:
    """問題ファイルを読み込む"""
    try:
        if Path(questions_file).exists():
            with open(questions_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            st.warning(f"問題ファイルが見つかりません: {questions_file}")
            return []
    except Exception as e:
        st.error(f"問題ファイルの読み込みエラー: {e}")
        return []


# ===== ログイン画面 =====

def show_login_page():
    """Azure AD SSO ログイン画面"""
    st.markdown("<h1 class='main-header'>📚 E-ラーニングシステム</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    
    with col2:
        st.markdown("## ログイン")
        st.info("🔐 Microsoftアカウント（Teams のアカウント）でサインインしてください")
        
        config = load_config()
        employees_mapping = load_employees_csv()
        
        if st.button("🔵 Microsoftでサインイン", use_container_width=True, type="primary"):
            result = authenticate_with_azure_ad(config, employees_mapping)
            
            if result["status"] == "success":
                # セッションに保存
                st.session_state.email = result["email"]
                st.session_state.full_name = result["full_name"]
                st.session_state.employee_id = result["employee_id"]
                st.session_state.username = result["employee_id"]
                st.session_state.role = "student"  # デフォルトロール
                st.session_state.current_page = "dashboard"
                
                # データベースにユーザーを登録
                db = DatabaseManager()
                user_id = db.authenticate_user(result["employee_id"], "azure_sso")
                if not user_id:
                    # ユーザーが存在しない場合は作成
                    db.add_user(
                        result["employee_id"],
                        "azure_sso_placeholder",
                        result["email"],
                        result["full_name"],
                        "student"
                    )
                    user_id = db.authenticate_user(result["employee_id"], "azure_sso_placeholder")
                
                st.session_state.user_id = user_id
                st.success("✅ ログインしました")
                st.rerun()
            else:
                st.error(f"❌ ログイン失敗\n\n{result['message']}")
        
        st.divider()
        st.markdown("### ℹ️ サインインについて")
        st.markdown("""
        - Teamsと同じメールアドレス＆パスワードでサインインしてください
        - 初回は同意画面が表示されます
        - 社員マスターにないメールアドレスではサインインできません
        """)


# ===== ダッシュボード（ホーム） =====

def show_dashboard():
    """ユーザーダッシュボード"""
    db = DatabaseManager()
    config = load_config()
    
    st.markdown(f"<h1 class='main-header'>🏠 ホーム</h1>", unsafe_allow_html=True)
    
    # ユーザー情報を表示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("社員番号", st.session_state.employee_id)
    with col2:
        st.metric("フルネーム", st.session_state.full_name)
    with col3:
        st.metric("メール", st.session_state.email.split('@')[0] + "@...")
    
    st.divider()
    
    # コース一覧
    st.markdown("## 📖 利用可能なコース")
    
    courses = db.get_courses()
    
    if not courses:
        st.info("現在利用可能なコースがありません")
        return
    
    for course in courses:
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            st.subheader(course['course_name'])
            st.write(course['description'])
        
        with col2:
            # 成績表示
            score = db.get_user_course_score(st.session_state.user_id, course['course_id'])
            if score:
                percent = score['score_percent']
                if score['passed']:
                    st.markdown(f"<div class='status-passed'>✅ 合格 {percent:.1f}%</div>", 
                               unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='status-failed'>❌ 不合格 {percent:.1f}%</div>", 
                               unsafe_allow_html=True)
            else:
                st.write("未実施")
        
        with col3:
            if st.button("学習を開始", key=f"start_{course['course_id']}", use_container_width=True):
                st.session_state.current_page = "learning"
                st.session_state.current_course_id = course['course_id']
                st.session_state.current_course_name = course['course_name']
                st.session_state.current_course_pdf = course.get('pdf_path', '')
                st.session_state.quiz_time_limit = course['quiz_time_limit']
                st.session_state.passing_score = course['passing_score']
                st.rerun()


# ===== 学習画面 =====

def show_learning_page():
    """学習画面（教本表示）"""
    db = DatabaseManager()
    config = load_config()
    
    st.markdown(f"<h1 class='main-header'>📘 {st.session_state.current_course_name}</h1>", 
               unsafe_allow_html=True)
    
    # 戻るボタン
    if st.button("← ダッシュボードに戻る"):
        st.session_state.current_page = "dashboard"
        st.rerun()
    
    st.divider()
    
    # PDFファイルを表示
    pdf_path = st.session_state.current_course_pdf
    
    if pdf_path and Path(pdf_path).exists():
        st.markdown("## 📄 教本")
        st.info("PDFを確認してから、クイズに進んでください")
        
        # PDFを埋め込み表示
        with open(pdf_path, 'rb') as pdf_file:
            pdf_bytes = pdf_file.read()
            st.download_button(
                label="PDFをダウンロード",
                data=pdf_bytes,
                file_name=Path(pdf_path).name,
                mime="application/pdf"
            )
    else:
        st.warning(f"教本ファイルが見つかりません: {pdf_path}")
    
    st.divider()
    
    # クイズ開始ボタン
    st.markdown("## ✏️ クイズ")
    st.info(f"⏱️ 回答時間: {st.session_state.quiz_time_limit}秒")
    
    if st.button("クイズを開始する", use_container_width=True, type="primary"):
        st.session_state.current_page = "quiz"
        st.session_state.quiz_started = True
        st.session_state.quiz_start_time = datetime.now()
        st.session_state.quiz_answers = {}
        st.rerun()


# ===== クイズ画面 =====

def show_quiz_page():
    """クイズ実施画面"""
    db = DatabaseManager()
    config = load_config()
    questions = load_questions()
    
    st.markdown(f"<h1 class='main-header'>❓ クイズ: {st.session_state.current_course_name}</h1>", 
               unsafe_allow_html=True)
    
    # タイマー表示
    elapsed_time = (datetime.now() - st.session_state.quiz_start_time).total_seconds()
    remaining_time = st.session_state.quiz_time_limit - elapsed_time
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if remaining_time > 0:
            st.metric("⏱️ 残り時間", f"{int(remaining_time)}秒")
        else:
            st.metric("⏱️ 時間切れ", "0秒")
            st.warning("⚠️ 回答時間切れです。自動提出します。")
            # 自動提出ロジック
            submit_quiz(questions, db, config)
            return
    
    st.divider()
    
    # クイズ問題を表示
    for q in questions:
        st.markdown(f"### 問題 {q['id']}: {q['question']}")
        
        # 複数選択か単一選択かで異なるUI
        if q.get('multiple_choice', False):
            st.info("複数選択可")
            answers = st.multiselect(
                "回答を選択してください（複数選択可）",
                [f"{c['letter']}. {c['text']}" for c in q['choices']],
                key=f"question_{q['id']}"
            )
            selected_letters = [a.split(".")[0] for a in answers]
        else:
            st.info("単一選択")
            answer = st.radio(
                "回答を選択してください",
                [f"{c['letter']}. {c['text']}" for c in q['choices']],
                key=f"question_{q['id']}"
            )
            selected_letters = [answer.split(".")[0]] if answer else []
        
        st.session_state.quiz_answers[q['id']] = selected_letters
        st.divider()
    
    # 送信ボタン
    col1, col2 = st.columns(2)
    with col1:
        if st.button("回答を送信", use_container_width=True, type="primary"):
            submit_quiz(questions, db, config)
            return
    
    with col2:
        if st.button("キャンセル", use_container_width=True):
            st.session_state.current_page = "learning"
            st.session_state.quiz_started = False
            st.rerun()


def submit_quiz(questions: List[Dict], db: DatabaseManager, config: Dict):
    """クイズを採点して結果を表示"""
    # 採点ロジック
    total_score = 0
    max_score = 0
    correct_count = 0
    
    for q in questions:
        max_score += config['quiz'].get('points_per_question', 20)
        
        selected = st.session_state.quiz_answers.get(q['id'], [])
        correct_answers = q['correct_answers']
        
        is_correct = set(selected) == set(correct_answers)
        
        if is_correct:
            total_score += config['quiz'].get('points_per_question', 20)
            correct_count += 1
        
        # データベースに保存
        db.save_quiz_result(
            st.session_state.user_id,
            st.session_state.current_course_id,
            q['id'],
            selected,
            is_correct,
            config['quiz'].get('points_per_question', 20) if is_correct else 0
        )
    
    # 成績を計算
    score_percent = (total_score / max_score * 100) if max_score > 0 else 0
    passed = score_percent >= st.session_state.passing_score
    
    # 成績を保存
    db.save_course_score(
        st.session_state.user_id,
        st.session_state.current_course_id,
        total_score,
        max_score,
        st.session_state.passing_score
    )
    
    # 通知を送信
    notifier = EmailNotifier()
    
    if st.session_state.email:
        notifier.send_quiz_completion_email(
            st.session_state.full_name,
            st.session_state.email,
            st.session_state.current_course_name,
            score_percent,
            total_score,
            max_score,
            passed
        )
    
    notifier.send_admin_notification(
        st.session_state.full_name,
        st.session_state.email,
        st.session_state.current_course_name,
        score_percent,
        total_score,
        max_score,
        passed
    )
    
    # 結果表示画面に遷移
    st.session_state.current_page = "result"
    st.session_state.result_score = total_score
    st.session_state.result_max_score = max_score
    st.session_state.result_percent = score_percent
    st.session_state.result_passed = passed
    st.session_state.result_correct = correct_count
    st.session_state.result_total = len(questions)
    st.rerun()


# ===== 結果表示画面 =====

def show_result_page():
    """クイズ結果表示"""
    st.markdown("<h1 class='main-header'>🎓 クイズ結果</h1>", unsafe_allow_html=True)
    
    # 結果サマリー
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("得点", f"{st.session_state.result_score}/{st.session_state.result_max_score}")
    
    with col2:
        st.metric("正答率", f"{st.session_state.result_percent:.1f}%")
    
    with col3:
        st.metric("正答数", f"{st.session_state.result_correct}/{st.session_state.result_total}")
    
    st.divider()
    
    # 判定
    if st.session_state.result_passed:
        st.markdown(f"<div class='status-passed'>✅ 合格です。おめでとうございます！</div>", 
                   unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='status-failed'>❌ 不合格です。もう一度挑戦してください。</div>", 
                   unsafe_allow_html=True)
    
    st.divider()
    
    # ナビゲーション
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("クイズを再実施", use_container_width=True):
            st.session_state.current_page = "quiz"
            st.session_state.quiz_started = True
            st.session_state.quiz_start_time = datetime.now()
            st.session_state.quiz_answers = {}
            st.rerun()
    
    with col2:
        if st.button("ダッシュボードに戻る", use_container_width=True):
            st.session_state.current_page = "dashboard"
            st.rerun()


# ===== メイン処理 =====

def main():
    """メイン処理"""
    init_session_state()
    
    # ログアウトボタン（ヘッダー）
    if st.session_state.user_id:
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col3:
            if st.button("ログアウト"):
                st.session_state.user_id = None
                st.session_state.username = None
                st.session_state.email = None
                st.session_state.full_name = None
                st.session_state.employee_id = None
                st.session_state.role = None
                st.session_state.current_page = "login"
                st.rerun()
        
        with col2:
            st.write(f"社員番号: {st.session_state.employee_id}")
    
    # ページ切り替え
    if not st.session_state.user_id:
        show_login_page()
    
    elif st.session_state.current_page == "dashboard":
        show_dashboard()
    
    elif st.session_state.current_page == "learning":
        show_learning_page()
    
    elif st.session_state.current_page == "quiz":
        show_quiz_page()
    
    elif st.session_state.current_page == "result":
        show_result_page()
    
    # フッター
    st.divider()
    st.markdown("---")
    st.markdown(
        "© 2024 E-ラーニングシステム (Azure AD SSO版) | "
        "Powered by Streamlit + Microsoft Azure AD | "
        "[README](https://github.com/your-repo) | "
        "[サポート](mailto:admin@example.com)"
    )


if __name__ == "__main__":
    main()
