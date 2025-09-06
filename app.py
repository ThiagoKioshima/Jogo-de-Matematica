import os
import logging
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
import random
from datetime import datetime

# Configura o log
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Cria o aplicativo
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default_secret_key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configura o banco de dados
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///mathgame.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Inicializa o aplicativo com a extensão
db.init_app(app)

with app.app_context():
    import models
    db.create_all()

# Configuração do jogo
DIFFICULTY_SETTINGS = {
    'easy': {
        'max_number': 10,
        'operations': ['+', '-'],
        'time_limit': 30
    },
    'medium': {
        'max_number': 50,
        'operations': ['+', '-', '*'],
        'time_limit': 20
    },
    'hard': {
        'max_number': 100,
        'operations': ['+', '-', '*', '/'],
        'time_limit': 15
    }
}

def generate_question(difficulty):
    """Gera uma pergunta de matemática com base no nível de dificuldade"""
    settings = DIFFICULTY_SETTINGS[difficulty]
    operation = random.choice(settings['operations'])
    
    # Inicializa variáveis
    question = ""
    answer = 0

    if operation == '+':
        num1 = random.randint(1, settings['max_number'])
        num2 = random.randint(1, settings['max_number'])
        answer = num1 + num2
        question = f"{num1} + {num2}"

    elif operation == '-':
        num1 = random.randint(1, settings['max_number'])
        num2 = random.randint(1, num1)  # Garante um resultado positivo
        answer = num1 - num2
        question = f"{num1} - {num2}"

    elif operation == '*':
        num1 = random.randint(1, min(settings['max_number'] // 5, 12))
        num2 = random.randint(1, min(settings['max_number'] // 5, 12))
        answer = num1 * num2
        question = f"{num1} × {num2}"

    elif operation == '/':
        # Gera uma divisão que resulta em números inteiros
        answer = random.randint(1, min(settings['max_number'] // 5, 12))
        num2 = random.randint(2, min(settings['max_number'] // 10, 10))
        num1 = answer * num2
        question = f"{num1} ÷ {num2}"

    return {
        'question': question,
        'answer': answer,
        'time_limit': settings['time_limit']
    }

@app.route('/')
def index():
    """Página principal do jogo"""
    return render_template('index.html')

@app.route('/start_game', methods=['POST'])
def start_game():
    """Inicia um novo jogo com a dificuldade selecionada"""
    data = request.get_json()
    difficulty = data.get('difficulty', 'easy')

    # Inicializa a sessão do jogo
    session['game_active'] = True
    session['difficulty'] = difficulty
    session['score'] = 0
    session['total_questions'] = 0
    session['correct_answers'] = 0
    session['start_time'] = datetime.now().isoformat()

    # Gera a primeira pergunta
    question_data = generate_question(difficulty)
    session['current_question'] = question_data
    session['question_start_time'] = datetime.now().isoformat()

    return jsonify({
        'success': True,
        'question': question_data['question'],
        'time_limit': question_data['time_limit']
    })

@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    """Envia uma resposta e obtém a próxima pergunta"""
    if not session.get('game_active'):
        return jsonify({'success': False, 'error': 'Nenhum jogo ativo'})

    data = request.get_json()
    user_answer = data.get('answer')

    current_question = session.get('current_question')
    if not current_question:
        return jsonify({'success': False, 'error': 'Nenhuma pergunta atual'})

    try:
        user_answer = int(user_answer)
    except (ValueError, TypeError):
        user_answer = None

    correct_answer = current_question['answer']
    is_correct = user_answer == correct_answer

    # Atualiza as estatísticas
    session['total_questions'] += 1
    if is_correct:
        session['correct_answers'] += 1
        session['score'] += 10  # 10 pontos por resposta correta

    # Calcula o tempo gasto
    question_start = datetime.fromisoformat(session['question_start_time'])
    time_taken = (datetime.now() - question_start).total_seconds()

    # Pontos de bônus para respostas rápidas (se respondida em menos da metade do tempo limite)
    if is_correct and time_taken < (current_question['time_limit'] / 2):
        bonus_points = max(1, int(10 - time_taken))
        session['score'] += bonus_points

    # Gera a próxima pergunta
    next_question = generate_question(session['difficulty'])
    session['current_question'] = next_question
    session['question_start_time'] = datetime.now().isoformat()

    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_answer': correct_answer,
        'score': session['score'],
        'next_question': next_question['question'],
        'time_limit': next_question['time_limit'],
        'total_questions': session['total_questions'],
        'correct_answers': session['correct_answers']
    })

@app.route('/end_game', methods=['POST'])
def end_game():
    """Finaliza o jogo atual e salva os resultados"""
    if not session.get('game_active'):
        return jsonify({'success': False, 'error': 'Nenhum jogo ativo'})

    # Calcula as estatísticas finais
    game_duration = (datetime.now() - datetime.fromisoformat(session['start_time'])).total_seconds()
    accuracy = (session['correct_answers'] / session['total_questions'] * 100) if session['total_questions'] > 0 else 0

    # Salva o resultado do jogo no banco de dados
    game_result = models.GameResult()
    game_result.difficulty = session['difficulty']
    game_result.score = session['score']
    game_result.total_questions = session['total_questions']
    game_result.correct_answers = session['correct_answers']
    game_result.accuracy = accuracy
    game_result.duration = game_duration

    db.session.add(game_result)
    db.session.commit()

    final_stats = {
        'score': session['score'],
        'total_questions': session['total_questions'],
        'correct_answers': session['correct_answers'],
        'accuracy': round(accuracy, 1),
        'duration': round(game_duration, 1),
        'difficulty': session['difficulty']
    }

    # Limpa a sessão do jogo
    session['game_active'] = False

    return jsonify({
        'success': True,
        'final_stats': final_stats
    })

@app.route('/get_leaderboard')
def get_leaderboard():
    """Obtém as melhores pontuações para o ranking"""
    top_scores = models.GameResult.query.order_by(models.GameResult.score.desc()).limit(10).all()

    leaderboard = []
    for result in top_scores:
        leaderboard.append({
            'score': result.score,
            'difficulty': result.difficulty,
            'accuracy': round(result.accuracy, 1),
            'date': result.created_at.strftime('%Y-%m-%d')
        })

    return jsonify({'leaderboard': leaderboard})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
