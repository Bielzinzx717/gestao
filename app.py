from flask import Flask, render_template, redirect, url_for, request, flash, make_response
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, login_manager
from models import Usuario, Transacao
from datetime import datetime, timedelta
import os
from sqlalchemy import func, case
import csv
from io import StringIO, BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from flask_wtf.csrf import CSRFProtect
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://usuario:senha@host/banco'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None

db.init_app(app)
login_manager.init_app(app)
csrf = CSRFProtect(app)

def validar_senha_forte(senha):
    """
    Valida se a senha atende aos requisitos mínimos de segurança:
    - Mínimo 8 caracteres
    - Pelo menos uma letra maiúscula
    - Pelo menos uma letra minúscula
    - Pelo menos um número
    - Pelo menos um caractere especial
    """
    if len(senha) < 8:
        return False, "A senha deve ter no mínimo 8 caracteres."
    
    if not re.search(r'[A-Z]', senha):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    
    if not re.search(r'[a-z]', senha):
        return False, "A senha deve conter pelo menos uma letra minúscula."
    
    if not re.search(r'\d', senha):
        return False, "A senha deve conter pelo menos um número."
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', senha):
        return False, "A senha deve conter pelo menos um caractere especial (!@#$%^&*(),.?\":{}|<>)."
    
    return True, "Senha válida."

def sanitizar_texto(texto):
    """Remove caracteres potencialmente perigosos de inputs de texto"""
    if not texto:
        return texto
    # Remove tags HTML e scripts
    texto = re.sub(r'<[^>]*>', '', texto)
    # Remove caracteres de controle
    texto = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', texto)
    return texto.strip()

def validar_email(email):
    """Valida formato de email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nome = sanitizar_texto(request.form.get('nome', '').strip())
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not nome or len(nome) < 2:
            flash('Nome deve ter pelo menos 2 caracteres.', 'error')
            return redirect(url_for('register'))
        
        if not validar_email(email):
            flash('E-mail inválido.', 'error')
            return redirect(url_for('register'))

        if Usuario.query.filter_by(email=email).first():
            flash('E-mail já cadastrado!', 'error')
            return redirect(url_for('register'))

        senha_valida, mensagem = validar_senha_forte(senha)
        if not senha_valida:
            flash(mensagem, 'error')
            return redirect(url_for('register'))

        try:
            novo_usuario = Usuario(nome=nome, email=email)
            novo_usuario.set_password(senha)
            db.session.add(novo_usuario)
            db.session.commit()
            flash('Cadastro realizado com sucesso! Faça o login.', 'success')
            return redirect(url_for('login'))
        except ValueError as e:
            flash(str(e), 'error')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not validar_email(email):
            flash('E-mail ou senha inválidos.', 'error')
            return redirect(url_for('login'))

        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and usuario.check_password(senha):
            login_user(usuario)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('E-mail ou senha inválidos.', 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('login'))

@app.route('/definir_meta', methods=['POST'])
@login_required
def definir_meta():
    try:
        meta = float(request.form.get('meta_mensal', 0))
        if meta < 0:
            flash('A meta deve ser um valor positivo.', 'error')
        elif meta > 999999999:
            flash('Valor da meta muito alto.', 'error')
        else:
            current_user.meta_mensal = meta
            db.session.commit()
            flash(f'Meta mensal definida para R$ {meta:.2f}!', 'success')
    except (ValueError, TypeError):
        flash('Valor inválido para meta.', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    data_inicial_str = request.args.get('data_inicial')
    data_final_str = request.args.get('data_final')
    filtro_tipo = request.args.get('tipo')
    filtro_categoria = request.args.get('categoria')
    filtro_busca = request.args.get('busca')

    data_inicial = None
    data_final = None

    query_base = Transacao.query.filter_by(usuario_id=current_user.id)
    query_filtrada = query_base

    if data_inicial_str:
        try:
            data_inicial = datetime.strptime(data_inicial_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data >= data_inicial)
        except ValueError:
            flash('Formato de Data Inicial inválido.', 'error')
            data_inicial_str = None

    if data_final_str:
        try:
            data_final = datetime.strptime(data_final_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data <= data_final)
        except ValueError:
            flash('Formato de Data Final inválido.', 'error')
            data_final_str = None

    if filtro_tipo and filtro_tipo != 'todos':
        query_filtrada = query_filtrada.filter(Transacao.tipo == filtro_tipo)
    
    if filtro_categoria and filtro_categoria != 'todas':
        query_filtrada = query_filtrada.filter(Transacao.categoria == filtro_categoria)
    
    if filtro_busca:
        query_filtrada = query_filtrada.filter(Transacao.descricao.ilike(f'%{filtro_busca}%'))

    categorias_disponiveis = db.session.query(Transacao.categoria).filter_by(usuario_id=current_user.id).distinct().all()
    categorias_disponiveis = [c[0] for c in categorias_disponiveis]

    mes_atual = datetime.now().strftime('%Y-%m')
    mes_anterior = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    
    gastos_por_categoria = db.session.query(
        Transacao.categoria,
        func.sum(Transacao.valor).label('total')
    ).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'despesa',
        func.strftime('%Y-%m', Transacao.data) == mes_atual
    ).group_by(Transacao.categoria).order_by(func.sum(Transacao.valor).desc()).limit(5).all()
    
    top_categorias = [{'categoria': cat, 'total': total} for cat, total in gastos_por_categoria]
    
    despesas_mes_atual = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'despesa',
        func.strftime('%Y-%m', Transacao.data) == mes_atual
    ).scalar() or 0.0
    
    receitas_mes_atual = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'receita',
        func.strftime('%Y-%m', Transacao.data) == mes_atual
    ).scalar() or 0.0
    
    despesas_mes_anterior = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'despesa',
        func.strftime('%Y-%m', Transacao.data) == mes_anterior
    ).scalar() or 0.0
    
    receitas_mes_anterior = db.session.query(func.sum(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'receita',
        func.strftime('%Y-%m', Transacao.data) == mes_anterior
    ).scalar() or 0.0
    
    comparacao_mensal = {
        'mes_atual': mes_atual,
        'mes_anterior': mes_anterior,
        'receitas_atual': receitas_mes_atual,
        'receitas_anterior': receitas_mes_anterior,
        'despesas_atual': despesas_mes_atual,
        'despesas_anterior': despesas_mes_anterior,
        'variacao_receitas': receitas_mes_atual - receitas_mes_anterior,
        'variacao_despesas': despesas_mes_atual - despesas_mes_anterior
    }
    
    tres_meses_atras = (datetime.now().replace(day=1) - timedelta(days=90)).strftime('%Y-%m')
    
    media_despesas = db.session.query(func.avg(Transacao.valor)).filter(
        Transacao.usuario_id == current_user.id,
        Transacao.tipo == 'despesa',
        func.strftime('%Y-%m', Transacao.data) >= tres_meses_atras
    ).scalar() or 0.0
    
    dias_no_mes = datetime.now().day
    dias_totais_mes = (datetime.now().replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    dias_totais_mes = dias_totais_mes.day
    
    previsao_gastos = (despesas_mes_atual / dias_no_mes) * dias_totais_mes if dias_no_mes > 0 else 0
    
    estatisticas = {
        'top_categorias': top_categorias,
        'comparacao_mensal': comparacao_mensal,
        'previsao_gastos': previsao_gastos,
        'media_despesas_3meses': media_despesas
    }

    if data_inicial_str and data_final_str:
        transacoes = query_filtrada.order_by(Transacao.data.desc()).all()
        total_receitas = sum(t.valor for t in transacoes if t.tipo == 'receita')
        total_despesas = sum(t.valor for t in transacoes if t.tipo == 'despesa')
        saldo = total_receitas - total_despesas

        return render_template('dashboard.html',
                               transacoes=transacoes,
                               total_receitas=total_receitas,
                               total_despesas=total_despesas,
                               saldo=saldo,
                               relatorio_mensal=None,
                               data_inicial_str=data_inicial_str,
                               data_final_str=data_final_str,
                               filtro_tipo=filtro_tipo,
                               filtro_categoria=filtro_categoria,
                               filtro_busca=filtro_busca,
                               categorias_disponiveis=categorias_disponiveis,
                               estatisticas=estatisticas)

    else:
        relatorio_mensal_raw = db.session.query(
            func.strftime('%Y-%m', Transacao.data).label('mes_ano'),
            func.sum(case((Transacao.tipo == 'receita', Transacao.valor), else_=0)).label('total_receitas'),
            func.sum(case((Transacao.tipo == 'despesa', Transacao.valor), else_=0)).label('total_despesas')
        ).filter_by(usuario_id=current_user.id).group_by('mes_ano').order_by(func.strftime('%Y-%m', Transacao.data).desc()).all()

        relatorio_mensal = []
        total_receitas_geral = 0
        total_despesas_geral = 0

        for mes_ano, receitas, despesas in relatorio_mensal_raw:
            saldo_mes = receitas - despesas
            relatorio_mensal.append({
                'mes_ano': mes_ano,
                'total_receitas': receitas,
                'total_despesas': despesas,
                'saldo': saldo_mes
            })
            total_receitas_geral += receitas
            total_despesas_geral += despesas

        saldo_geral = total_receitas_geral - total_despesas_geral

        transacoes = query_filtrada.order_by(Transacao.data.desc()).limit(10).all()
        
        if filtro_tipo or filtro_categoria or filtro_busca:
            todas_transacoes_filtradas = query_filtrada.all()
            total_receitas_geral = sum(t.valor for t in todas_transacoes_filtradas if t.tipo == 'receita')
            total_despesas_geral = sum(t.valor for t in todas_transacoes_filtradas if t.tipo == 'despesa')
            saldo_geral = total_receitas_geral - total_despesas_geral

        return render_template('dashboard.html',
                               transacoes=transacoes,
                               total_receitas=total_receitas_geral,
                               total_despesas=total_despesas_geral,
                               saldo=saldo_geral,
                               relatorio_mensal=relatorio_mensal,
                               data_inicial_str=None,
                               data_final_str=None,
                               filtro_tipo=filtro_tipo,
                               filtro_categoria=filtro_categoria,
                               filtro_busca=filtro_busca,
                               categorias_disponiveis=categorias_disponiveis,
                               estatisticas=estatisticas)

@app.route('/nova', methods=['GET', 'POST'])
@login_required
def nova_transacao():
    if request.method == 'POST':
        descricao = sanitizar_texto(request.form.get('descricao', '').strip())
        categoria = sanitizar_texto(request.form.get('categoria', '').strip())
        tipo = request.form.get('tipo', '')
        
        if not descricao or len(descricao) < 2:
            flash('Descrição deve ter pelo menos 2 caracteres.', 'error')
            return redirect(url_for('nova_transacao'))
        
        if tipo not in ['receita', 'despesa']:
            flash('Tipo de transação inválido.', 'error')
            return redirect(url_for('nova_transacao'))
        
        try:
            valor = float(request.form.get('valor', 0))
            if valor <= 0:
                flash('Valor deve ser maior que zero.', 'error')
                return redirect(url_for('nova_transacao'))
            if valor > 999999999:
                flash('Valor muito alto.', 'error')
                return redirect(url_for('nova_transacao'))
        except (ValueError, TypeError):
            flash('Valor inválido.', 'error')
            return redirect(url_for('nova_transacao'))
        
        try:
            data = datetime.strptime(request.form.get('data', ''), '%Y-%m-%d')
        except ValueError:
            flash('Data inválida.', 'error')
            return redirect(url_for('nova_transacao'))

        transacao = Transacao(
            descricao=descricao,
            valor=valor,
            tipo=tipo,
            categoria=categoria,
            data=data,
            usuario_id=current_user.id
        )
        db.session.add(transacao)
        db.session.commit()
        flash('Transação adicionada!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('transaction_form.html')

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    transacao = Transacao.query.get_or_404(id)
    if transacao.usuario_id != current_user.id:
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))

    db.session.delete(transacao)
    db.session.commit()
    flash('Transação excluída.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_transacao(id):
    transacao = Transacao.query.get_or_404(id)
    
    if transacao.usuario_id != current_user.id:
        flash('Acesso negado.', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        descricao = sanitizar_texto(request.form.get('descricao', '').strip())
        categoria = sanitizar_texto(request.form.get('categoria', '').strip())
        tipo = request.form.get('tipo', '')
        
        if not descricao or len(descricao) < 2:
            flash('Descrição deve ter pelo menos 2 caracteres.', 'error')
            return redirect(url_for('editar_transacao', id=id))
        
        if tipo not in ['receita', 'despesa']:
            flash('Tipo de transação inválido.', 'error')
            return redirect(url_for('editar_transacao', id=id))
        
        try:
            valor = float(request.form.get('valor', 0))
            if valor <= 0:
                flash('Valor deve ser maior que zero.', 'error')
                return redirect(url_for('editar_transacao', id=id))
            if valor > 999999999:
                flash('Valor muito alto.', 'error')
                return redirect(url_for('editar_transacao', id=id))
        except (ValueError, TypeError):
            flash('Valor inválido.', 'error')
            return redirect(url_for('editar_transacao', id=id))
        
        try:
            data = datetime.strptime(request.form.get('data', ''), '%Y-%m-%d')
        except ValueError:
            flash('Data inválida.', 'error')
            return redirect(url_for('editar_transacao', id=id))
        
        transacao.descricao = descricao
        transacao.valor = valor
        transacao.tipo = tipo
        transacao.categoria = categoria
        transacao.data = data
        
        db.session.commit()
        flash('Transação atualizada com sucesso!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('transaction_form.html', transacao=transacao)

@app.route('/export/csv')
@login_required
def export_csv():
    # Aplicar os mesmos filtros do dashboard
    data_inicial_str = request.args.get('data_inicial')
    data_final_str = request.args.get('data_final')
    filtro_tipo = request.args.get('tipo')
    filtro_categoria = request.args.get('categoria')
    filtro_busca = request.args.get('busca')

    query_filtrada = Transacao.query.filter_by(usuario_id=current_user.id)

    if data_inicial_str:
        try:
            data_inicial = datetime.strptime(data_inicial_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data >= data_inicial)
        except ValueError:
            pass

    if data_final_str:
        try:
            data_final = datetime.strptime(data_final_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data <= data_final)
        except ValueError:
            pass

    if filtro_tipo and filtro_tipo != 'todos':
        query_filtrada = query_filtrada.filter(Transacao.tipo == filtro_tipo)
    
    if filtro_categoria and filtro_categoria != 'todas':
        query_filtrada = query_filtrada.filter(Transacao.categoria == filtro_categoria)
    
    if filtro_busca:
        query_filtrada = query_filtrada.filter(Transacao.descricao.ilike(f'%{filtro_busca}%'))

    transacoes = query_filtrada.order_by(Transacao.data.desc()).all()

    # Criar CSV em memória
    si = StringIO()
    writer = csv.writer(si)
    
    # Cabeçalho
    writer.writerow(['Data', 'Descrição', 'Tipo', 'Categoria', 'Valor'])
    
    # Dados
    for t in transacoes:
        writer.writerow([
            t.data.strftime('%d/%m/%Y'),
            t.descricao,
            t.tipo.capitalize(),
            t.categoria or 'Sem categoria',
            f'R$ {t.valor:.2f}'
        ])
    
    # Criar resposta
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=transacoes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    
    return output

@app.route('/export/pdf')
@login_required
def export_pdf():
    # Aplicar os mesmos filtros do dashboard
    data_inicial_str = request.args.get('data_inicial')
    data_final_str = request.args.get('data_final')
    filtro_tipo = request.args.get('tipo')
    filtro_categoria = request.args.get('categoria')
    filtro_busca = request.args.get('busca')

    query_filtrada = Transacao.query.filter_by(usuario_id=current_user.id)

    if data_inicial_str:
        try:
            data_inicial = datetime.strptime(data_inicial_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data >= data_inicial)
        except ValueError:
            pass

    if data_final_str:
        try:
            data_final = datetime.strptime(data_final_str, '%Y-%m-%d').date()
            query_filtrada = query_filtrada.filter(Transacao.data <= data_final)
        except ValueError:
            pass

    if filtro_tipo and filtro_tipo != 'todos':
        query_filtrada = query_filtrada.filter(Transacao.tipo == filtro_tipo)
    
    if filtro_categoria and filtro_categoria != 'todas':
        query_filtrada = query_filtrada.filter(Transacao.categoria == filtro_categoria)
    
    if filtro_busca:
        query_filtrada = query_filtrada.filter(Transacao.descricao.ilike(f'%{filtro_busca}%'))

    transacoes = query_filtrada.order_by(Transacao.data.desc()).all()

    # Calcular totais
    total_receitas = sum(t.valor for t in transacoes if t.tipo == 'receita')
    total_despesas = sum(t.valor for t in transacoes if t.tipo == 'despesa')
    saldo = total_receitas - total_despesas

    # Criar PDF em memória
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30,
        alignment=1  # Centralizado
    )
    
    # Título
    title = Paragraph(f"Relatório Financeiro - {current_user.nome}", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.2*inch))
    
    # Informações do período
    periodo_text = f"Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
    if data_inicial_str and data_final_str:
        periodo_text += f"<br/>Período: {data_inicial_str} a {data_final_str}"
    periodo = Paragraph(periodo_text, styles['Normal'])
    elements.append(periodo)
    elements.append(Spacer(1, 0.3*inch))
    
    # Resumo financeiro
    resumo_data = [
        ['Resumo Financeiro', ''],
        ['Total de Receitas:', f'R$ {total_receitas:.2f}'],
        ['Total de Despesas:', f'R$ {total_despesas:.2f}'],
        ['Saldo:', f'R$ {saldo:.2f}']
    ]
    
    resumo_table = Table(resumo_data, colWidths=[3*inch, 2*inch])
    resumo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
    ]))
    
    elements.append(resumo_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Tabela de transações
    if transacoes:
        transacoes_title = Paragraph("Transações", styles['Heading2'])
        elements.append(transacoes_title)
        elements.append(Spacer(1, 0.2*inch))
        
        data = [['Data', 'Descrição', 'Tipo', 'Categoria', 'Valor']]
        
        for t in transacoes:
            data.append([
                t.data.strftime('%d/%m/%Y'),
                t.descricao[:30] + '...' if len(t.descricao) > 30 else t.descricao,
                t.tipo.capitalize(),
                (t.categoria[:15] + '...') if t.categoria and len(t.categoria) > 15 else (t.categoria or 'N/A'),
                f'R$ {t.valor:.2f}'
            ])
        
        table = Table(data, colWidths=[1*inch, 2.5*inch, 1*inch, 1.2*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
        elements.append(table)
    else:
        no_data = Paragraph("Nenhuma transação encontrada para o período selecionado.", styles['Normal'])
        elements.append(no_data)
    
    # Construir PDF
    doc.build(elements)
    
    # Criar resposta
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename=relatorio_financeiro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response.headers["Content-Type"] = "application/pdf"
    
    return response

if __name__ == '__main__':
    app.run(debug=True)

