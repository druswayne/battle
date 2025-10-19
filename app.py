from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from sqlalchemy import or_
import random
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tournament.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модели данных
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')  # active, completed

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    player1_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    player2_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    winner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_completed = db.Column(db.Boolean, default=False)
    
    # Связи
    tournament = db.relationship('Tournament', backref=db.backref('matches', lazy=True))
    player1 = db.relationship('User', foreign_keys=[player1_id], backref='matches_as_player1')
    player2 = db.relationship('User', foreign_keys=[player2_id], backref='matches_as_player2')
    winner = db.relationship('User', foreign_keys=[winner_id], backref='matches_won')

class TournamentParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    tournament = db.relationship('Tournament', backref=db.backref('participants', lazy=True))
    user = db.relationship('User', backref=db.backref('tournament_participations', lazy=True))

class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Декоратор для проверки авторизации администратора
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session or not session['admin_logged_in']:
            flash('Для доступа к админ-панели необходимо войти в систему', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Маршруты
@app.route('/')
def index():
    tournaments = Tournament.query.order_by(Tournament.created_at.desc()).all()
    return render_template('index.html', tournaments=tournaments)

@app.route('/admin')
@admin_required
def admin():
    users = User.query.order_by(User.name).all()
    tournaments = Tournament.query.order_by(Tournament.created_at.desc()).all()
    return render_template('admin.html', users=users, tournaments=tournaments)

@app.route('/add_user', methods=['POST'])
@admin_required
def add_user():
    names_input = request.form.get('name')
    if names_input:
        # Разделяем по запятой и очищаем от пробелов
        names = [name.strip() for name in names_input.split(',') if name.strip()]
        
        if not names:
            flash('Имя пользователя не может быть пустым!', 'error')
            return redirect(url_for('admin'))
        
        added_count = 0
        duplicate_count = 0
        
        for name in names:
            # Проверяем, существует ли уже пользователь с таким именем
            existing_user = User.query.filter_by(name=name).first()
            if existing_user:
                duplicate_count += 1
                continue
            
            user = User(name=name)
            db.session.add(user)
            added_count += 1
        
        try:
            db.session.commit()
            
            # Формируем сообщение в зависимости от результата
            if added_count > 0 and duplicate_count > 0:
                flash(f'Добавлено участников: {added_count}. Пропущено дубликатов: {duplicate_count}', 'warning')
            elif added_count > 0:
                if added_count == 1:
                    flash('Участник добавлен успешно!', 'success')
                else:
                    flash(f'Добавлено участников: {added_count}', 'success')
            elif duplicate_count > 0:
                flash('Все указанные участники уже существуют в системе!', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при добавлении участников: {str(e)}', 'error')
    else:
        flash('Имя пользователя не может быть пустым!', 'error')
    return redirect(url_for('admin'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Проверяем, участвует ли пользователь в активных турнирах
    active_participations = TournamentParticipant.query.filter_by(user_id=user_id).all()
    
    if active_participations:
        # Получаем названия турниров, в которых участвует пользователь
        tournament_names = []
        for participation in active_participations:
            tournament_names.append(participation.tournament.name)
        
        flash(f'Нельзя удалить пользователя {user.name}, так как он участвует в турнирах: {", ".join(tournament_names)}', 'error')
        return redirect(url_for('admin'))
    
    # Проверяем, есть ли матчи с участием этого пользователя
    matches_as_player1 = Match.query.filter_by(player1_id=user_id).count()
    matches_as_player2 = Match.query.filter_by(player2_id=user_id).count()
    matches_as_winner = Match.query.filter_by(winner_id=user_id).count()
    
    if matches_as_player1 > 0 or matches_as_player2 > 0 or matches_as_winner > 0:
        flash(f'Нельзя удалить пользователя {user.name}, так как он участвовал в матчах турниров', 'error')
        return redirect(url_for('admin'))
    
    try:
        # Если все проверки пройдены, удаляем пользователя
        db.session.delete(user)
        db.session.commit()
        flash(f'Пользователь {user.name} успешно удален!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении пользователя: {str(e)}', 'error')
    
    return redirect(url_for('admin'))

@app.route('/force_delete_user/<int:user_id>', methods=['POST'])
@admin_required
def force_delete_user(user_id):
    """Принудительное удаление пользователя со всеми связанными записями"""
    user = User.query.get_or_404(user_id)
    confirm = request.form.get('confirm')
    
    if confirm != 'DELETE_USER':
        flash('Неправильное подтверждение. Введите "DELETE_USER"', 'error')
        return redirect(url_for('admin'))
    
    try:
        # Удаляем все участия в турнирах
        TournamentParticipant.query.filter_by(user_id=user_id).delete()
        
        # Удаляем все матчи, где пользователь был игроком или победителем
        Match.query.filter(
            or_(
                Match.player1_id == user_id,
                Match.player2_id == user_id,
                Match.winner_id == user_id
            )
        ).delete()
        
        # Удаляем самого пользователя
        db.session.delete(user)
        db.session.commit()
        
        flash(f'Пользователь {user.name} и все связанные данные принудительно удалены!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при принудительном удалении: {str(e)}', 'error')
    
    return redirect(url_for('admin'))

@app.route('/delete_tournament/<int:tournament_id>', methods=['POST'])
@admin_required
def delete_tournament(tournament_id):
    """Удаление турнира со всеми связанными данными"""
    tournament = Tournament.query.get_or_404(tournament_id)
    
    try:
        # Удаляем все матчи турнира
        Match.query.filter_by(tournament_id=tournament_id).delete()
        
        # Удаляем всех участников турнира
        TournamentParticipant.query.filter_by(tournament_id=tournament_id).delete()
        
        # Удаляем сам турнир
        db.session.delete(tournament)
        db.session.commit()
        
        flash(f'Турнир "{tournament.name}" и все связанные данные успешно удалены!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении турнира: {str(e)}', 'error')
    
    return redirect(url_for('admin'))

@app.route('/create_tournament', methods=['POST'])
@admin_required
def create_tournament():
    tournament_name = request.form.get('tournament_name', 'Турнир')
    selected_users = request.form.getlist('selected_users')
    
    if len(selected_users) < 2:
        flash('Для турнира нужно минимум 2 участника!', 'error')
        return redirect(url_for('admin'))
    
    # Создаем турнир
    tournament = Tournament(name=tournament_name)
    db.session.add(tournament)
    db.session.flush()  # Получаем ID турнира
    
    # Добавляем участников
    for user_id in selected_users:
        participant = TournamentParticipant(tournament_id=tournament.id, user_id=int(user_id))
        db.session.add(participant)
    
    # Создаем турнирную сетку
    create_tournament_bracket(tournament.id, selected_users)
    
    db.session.commit()
    flash('Турнир создан успешно!', 'success')
    return redirect(url_for('admin'))

def create_tournament_bracket(tournament_id, user_ids):
    """Создает турнирную сетку"""
    participants = [int(uid) for uid in user_ids]
    
    # Перемешиваем участников
    random.shuffle(participants)
    
    # Вычисляем количество раундов
    num_rounds = math.ceil(math.log2(len(participants)))
    
    # Создаем матчи для первого раунда
    current_round = participants.copy()
    round_num = 1
    
    while len(current_round) > 1:
        next_round = []
        
        # Создаем матчи для текущего раунда
        for i in range(0, len(current_round), 2):
            player1_id = current_round[i]
            player2_id = current_round[i + 1] if i + 1 < len(current_round) else None
            
            match = Match(
                tournament_id=tournament_id,
                round_number=round_num,
                player1_id=player1_id,
                player2_id=player2_id
            )
            db.session.add(match)
            
            # Если только один игрок (нечетное количество), он автоматически проходит
            if player2_id is None:
                match.winner_id = player1_id
                match.is_completed = True
                next_round.append(player1_id)
            else:
                # Добавляем placeholder для следующего раунда
                next_round.append(None)
        
        current_round = next_round
        round_num += 1

@app.route('/tournament/<int:tournament_id>')
def tournament_view(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    matches = Match.query.filter_by(tournament_id=tournament_id).order_by(Match.round_number, Match.id).all()
    
    # Группируем матчи по раундам
    rounds = {}
    for match in matches:
        if match.round_number not in rounds:
            rounds[match.round_number] = []
        rounds[match.round_number].append(match)
    
    # Определяем общее количество раундов на основе количества участников
    total_participants = len(tournament.participants)
    total_rounds = math.ceil(math.log2(total_participants)) if total_participants > 1 else 1
    
    # Создаем словарь названий раундов
    round_names = {}
    for round_num in rounds.keys():
        round_names[round_num] = get_round_name(round_num, total_rounds)
    
    return render_template('tournament.html', tournament=tournament, rounds=rounds, round_names=round_names)

@app.route('/set_winner', methods=['POST'])
@admin_required
def set_winner():
    match_id = request.form.get('match_id')
    winner_id = request.form.get('winner_id')
    
    match = Match.query.get_or_404(match_id)
    match.winner_id = int(winner_id)
    match.is_completed = True
    
    # Получаем информацию о победителе для сообщения
    winner = User.query.get(int(winner_id))
    
    # Проверяем, нужно ли создать матч следующего раунда
    create_next_round_match(match)
    
    db.session.commit()
    
    # Проверяем, повлияло ли это на создание следующего раунда
    next_round_matches = Match.query.filter_by(
        tournament_id=match.tournament_id,
        round_number=match.round_number + 1
    ).count()
    
    # Проверяем общее количество завершенных матчей в текущем раунде
    completed_in_current_round = Match.query.filter_by(
        tournament_id=match.tournament_id,
        round_number=match.round_number,
        is_completed=True
    ).count()
    
    total_in_current_round = Match.query.filter_by(
        tournament_id=match.tournament_id,
        round_number=match.round_number
    ).count()
    
    # Проверяем, завершен ли турнир
    tournament = Tournament.query.get(match.tournament_id)
    if tournament and tournament.status == 'completed':
        flash(f'🎉 ТУРНИР ЗАВЕРШЕН! Победитель турнира: {winner.name}! 🏆', 'success')
    elif next_round_matches > 0:
        flash(f'Победитель {winner.name} определен и перешел в следующий раунд!', 'success')
    elif completed_in_current_round == total_in_current_round:
        flash(f'Победитель {winner.name} определен! Следующий раунд создан!', 'success')
    else:
        flash(f'Победитель {winner.name} определен! Осталось {total_in_current_round - completed_in_current_round} матчей в раунде.', 'success')
    
    return redirect(url_for('tournament_view', tournament_id=match.tournament_id))

def create_next_round_match(current_match):
    """Создает матч следующего раунда, если это необходимо"""
    tournament_id = current_match.tournament_id
    current_round = current_match.round_number
    next_round = current_round + 1
    
    # Проверяем, не завершен ли уже турнир
    tournament = Tournament.query.get(tournament_id)
    if tournament and tournament.status == 'completed':
        return  # Турнир уже завершен, ничего не делаем
    
    # Получаем все завершенные матчи текущего раунда
    completed_matches = Match.query.filter_by(
        tournament_id=tournament_id,
        round_number=current_round,
        is_completed=True
    ).all()
    
    # Получаем общее количество матчей в текущем раунде
    total_matches_in_round = Match.query.filter_by(
        tournament_id=tournament_id,
        round_number=current_round
    ).count()
    
    # Если все матчи текущего раунда завершены, создаем следующий раунд
    if len(completed_matches) == total_matches_in_round:
        # Собираем всех победителей текущего раунда
        winners = [match.winner_id for match in completed_matches if match.winner_id is not None]
        
        if not winners:
            return
        
        # Если остается только один игрок, он автоматически выигрывает турнир
        if len(winners) == 1:
            # Обновляем статус турнира на завершенный
            if tournament:
                tournament.status = 'completed'
            return  # Не создаем следующий раунд, турнир завершен
        
        # Получаем уже существующие матчи следующего раунда
        existing_next_round_matches = Match.query.filter_by(
            tournament_id=tournament_id,
            round_number=next_round
        ).all()
        
        # Проверяем, есть ли матчи с None значениями и удаляем их
        invalid_matches = [match for match in existing_next_round_matches if match.player1_id is None or match.player2_id is None]
        if invalid_matches:
            for invalid_match in invalid_matches:
                db.session.delete(invalid_match)
            existing_next_round_matches = [match for match in existing_next_round_matches if match.player1_id is not None and match.player2_id is not None]
        
        # Если матчей следующего раунда еще нет, создаем их
        if len(existing_next_round_matches) == 0:
            # Создаем пары для следующего раунда
            for i in range(0, len(winners), 2):
                player1_id = winners[i]
                player2_id = winners[i + 1] if i + 1 < len(winners) else None
                
                # Если только один игрок (нечетное количество), он автоматически выигрывает турнир
                if player2_id is None:
                    # Обновляем статус турнира на завершенный
                    if tournament:
                        tournament.status = 'completed'
                    return  # Не создаем матч, турнир завершен
                else:
                    new_match = Match(
                        tournament_id=tournament_id,
                        round_number=next_round,
                        player1_id=player1_id,
                        player2_id=player2_id,
                        is_completed=False  # Новые матчи не завершены
                    )
                    db.session.add(new_match)

def get_round_name(round_number, total_rounds):
    """Определяет правильное название раунда в зависимости от общего количества раундов"""
    if round_number == total_rounds:
        return "Финал"
    elif round_number == total_rounds - 1:
        return "Полуфинал"
    elif round_number == total_rounds - 2:
        return "Четвертьфинал"
    elif round_number == total_rounds - 3:
        return "1/8 финала"
    elif round_number == total_rounds - 4:
        return "1/16 финала"
    else:
        return f"Раунд {round_number}"

# Роуты для авторизации администратора
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = AdminUser.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Вы успешно вошли в систему!', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Неверное имя пользователя или пароль!', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/admin/setup', methods=['GET', 'POST'])
def admin_setup():
    # Проверяем, есть ли уже администраторы
    if AdminUser.query.count() > 0:
        flash('Администратор уже настроен!', 'error')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not password:
            flash('Все поля обязательны для заполнения!', 'error')
            return redirect(url_for('admin_setup'))
        
        if password != confirm_password:
            flash('Пароли не совпадают!', 'error')
            return redirect(url_for('admin_setup'))
        
        if len(password) < 6:
            flash('Пароль должен содержать минимум 6 символов!', 'error')
            return redirect(url_for('admin_setup'))
        
        # Проверяем, не существует ли уже администратор с таким именем
        existing_admin = AdminUser.query.filter_by(username=username).first()
        if existing_admin:
            flash('Администратор с таким именем пользователя уже существует!', 'error')
            return redirect(url_for('admin_setup'))
        
        try:
            # Создаем администратора
            admin = AdminUser(username=username)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            
            flash('Администратор создан успешно! Теперь вы можете войти в систему.', 'success')
            return redirect(url_for('admin_login'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при создании администратора. Попробуйте другое имя пользователя.', 'error')
            return redirect(url_for('admin_setup'))
    
    return render_template('admin_setup.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=False)
