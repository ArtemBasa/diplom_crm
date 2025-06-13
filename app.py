from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3, io, csv
import os
from werkzeug.utils import secure_filename
import json
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key'
DATABASE = 'arka_crm.db'
UPLOAD_DIR = os.path.join(app.static_folder, 'uploads', 'products')
os.makedirs(UPLOAD_DIR, exist_ok=True)
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    c = db.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS user (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL,
      role TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS category (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS product (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT,
      price REAL NOT NULL,
      stock INTEGER DEFAULT 0,
      status TEXT DEFAULT 'in_stock',
      published INTEGER DEFAULT 1,
      discount REAL DEFAULT 0.0,
      category_id INTEGER,
      supplier_id INTEGER NOT NULL,
      FOREIGN KEY(category_id) REFERENCES category(id),
      FOREIGN KEY(supplier_id) REFERENCES user(id)
    );
    CREATE TABLE IF NOT EXISTS "order" (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      product_id INTEGER NOT NULL,
      dropshipper_id INTEGER NOT NULL,
      quantity INTEGER DEFAULT 1,
      recipient_name TEXT NOT NULL,
      address TEXT NOT NULL,
      comment TEXT,
      status TEXT DEFAULT 'new',
      tracking_number TEXT,
      paid INTEGER DEFAULT 0,
      FOREIGN KEY(product_id) REFERENCES product(id),
      FOREIGN KEY(dropshipper_id) REFERENCES user(id)
    );
    CREATE TABLE IF NOT EXISTS review (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      product_id INTEGER NOT NULL,
      supplier_id INTEGER NOT NULL,
      rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
      comment TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES user(id),
      FOREIGN KEY(product_id) REFERENCES product(id),
      FOREIGN KEY(supplier_id) REFERENCES user(id)
    );
    """)
    db.commit()
    db.close()

init_db()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def supplier_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'Supplier':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def dropshipper_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'Dropshipper':
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

@app.route('/')
def index():
    if 'user_id' in session:
        if session['role'] == 'Supplier':
            return redirect(url_for('supplier_dashboard'))
        elif session['role'] == 'Dropshipper':
            return redirect(url_for('dropshipper_dashboard'))
        else:
            return redirect(url_for('shop'))
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        u,p,r = request.form['username'], request.form['password'], request.form['role']
        db = get_db()
        if db.execute('SELECT 1 FROM user WHERE username=?', (u,)).fetchone():
            flash("Користувач з таким логіном уже існує", "danger")
            return redirect(url_for('register'))
        if db.execute('SELECT 1 FROM user WHERE username=?',(u,)).fetchone():
            flash("User exists"); return redirect(url_for('register'))
        db.execute('INSERT INTO user(username,password,role) VALUES(?,?,?)',
                   (u, generate_password_hash(p), r))
        db.commit(); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u,p = request.form['username'], request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM user WHERE username=?',(u,)).fetchone()
        if not (user and check_password_hash(user['password'], p)):
            flash("Неправильний логін або пароль", "danger")
            return redirect(url_for('login'))
        if user and check_password_hash(user['password'], p):
            session['user_id'], session['username'], session['role'] = user['id'], u, user['role']
            return redirect(url_for('index'))
        flash("Invalid credentials"); return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

# --- Supplier views ---

@app.route('/supplier')
@supplier_required
def supplier_dashboard():
    return render_template('supplier/dashboard.html')

@app.route('/supplier/products')
@supplier_required
def supplier_products():
    db = get_db()
    prods = db.execute('SELECT * FROM product WHERE supplier_id=?',(session['user_id'],)).fetchall()
    return render_template('supplier/products.html', products=prods)

@app.route('/supplier/products/add', methods=['GET','POST'])
@supplier_required
def supplier_add_product():
    db = get_db()
    cats = db.execute('SELECT * FROM category').fetchall()
    if request.method == 'POST':
        f = request.form
        cursor = db.execute('''
          INSERT INTO product(name,description,price,stock,status,published,discount,category_id,supplier_id)
          VALUES(?,?,?,?,?,?,?,?,?)
        ''', (
            f['name'], f['description'], float(f['price']), int(f['stock']),
            f['status'], 1, float(f.get('discount', 0)), f.get('category') or None,
            session['user_id']
        ))
        db.commit()
        pid = cursor.lastrowid

        # --- обробка фото ---
        photo = request.files.get('photo')
        if photo and photo.filename:
            ext = secure_filename(photo.filename).rsplit('.',1)[-1]
            product_folder = os.path.join(UPLOAD_DIR, str(pid))
            os.makedirs(product_folder, exist_ok=True)
            photo.save(os.path.join(product_folder, f'1.{ext}'))
        # ---------------------

        return redirect(url_for('supplier_products'))
    return render_template('supplier/edit_product.html', categories=cats, product=None)

@app.route('/supplier/products/edit/<int:pid>', methods=['GET','POST'])
@supplier_required
def supplier_edit_product(pid):
    db = get_db()
    prod = db.execute(
        'SELECT * FROM product WHERE id=? AND supplier_id=?',
        (pid, session['user_id'])
    ).fetchone()
    cats = db.execute('SELECT * FROM category').fetchall()
    if request.method == 'POST':
        f = request.form
        db.execute('''
          UPDATE product
          SET name=?,description=?,price=?,stock=?,status=?,published=?,discount=?,category_id=?
          WHERE id=?
        ''', (
            f['name'], f['description'], float(f['price']), int(f['stock']),
            f['status'], 1 if f.get('published') else 0, float(f.get('discount', 0)),
            f.get('category') or None, pid
        ))
        db.commit()

        # --- обробка нового фото, якщо завантажили ---
        photo = request.files.get('photo')
        if photo and photo.filename:
            ext = secure_filename(photo.filename).rsplit('.',1)[-1]
            product_folder = os.path.join(UPLOAD_DIR, str(pid))
            os.makedirs(product_folder, exist_ok=True)
            photo.save(os.path.join(product_folder, f'1.{ext}'))
        # ---------------------

        return redirect(url_for('supplier_products'))
    return render_template('supplier/edit_product.html', categories=cats, product=prod)

import io, csv

@app.route('/supplier/products/upload', methods=['GET','POST'])
@supplier_required
def supplier_upload_products():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash("Не вибрано файл", "danger")
            return redirect(url_for('supplier_upload_products'))

        raw = file.read()
        # Спробуємо кілька кодувань
        for enc in ('utf-8-sig', 'utf-8', 'cp1251', 'cp1252', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            flash("Неможливо прочитати файл у підтримуваному кодуванні", "danger")
            return redirect(url_for('supplier_upload_products'))

        # Визначаємо роздільник за першим рядком
        first = text.splitlines()[0]
        delimiter = '\t' if '\t' in first else ','

        stream = io.StringIO(text, newline=None)
        reader = csv.reader(stream, delimiter=delimiter)

        db = get_db()
        added = 0
        for row in reader:
            # Очищаємо порожні рядки та шапку
            if not row or row[0].strip().lower() in ('name', 'назва'):
                continue
            # Очікуємо мінімум 4 колонки
            if len(row) < 4:
                continue
            name, desc, price, stock = row[0], row[1], row[2], row[3]
            try:
                price = float(price)
                stock = int(stock)
            except ValueError:
                continue
            db.execute(
                'INSERT INTO product(name,description,price,stock,supplier_id) VALUES(?,?,?,?,?)',
                (name, desc, price, stock, session['user_id'])
            )
            added += 1
        db.commit()

        flash(f"Додано {added} товарів", "success")
        return redirect(url_for('supplier_products'))

    return render_template('supplier/upload_products.html')


@app.route('/supplier/categories')
@supplier_required
def supplier_categories():
    db = get_db()
    cats = db.execute('''
      SELECT c.id,
             c.name,
             COUNT(p.id) AS count
      FROM category c
      LEFT JOIN product p ON p.category_id = c.id AND p.supplier_id = ?
      GROUP BY c.id
    ''', (session['user_id'],)).fetchall()
    return render_template('supplier/categories.html', categories=cats)

@app.route('/supplier/categories/add', methods=['GET','POST'])
@supplier_required
def supplier_add_category():
    if request.method == 'POST':
        name = request.form['name'].strip()
        db = get_db()
        try:
            db.execute('INSERT INTO category(name) VALUES(?)', (name,))
            db.commit()
            flash("Категорію створено", "success")
            return redirect(url_for('supplier_categories'))
        except sqlite3.IntegrityError:
            flash("Категорія з такою назвою вже існує", "danger")
    return render_template('supplier/edit_category.html', category=None)
@app.route('/supplier/categories/edit/<int:cid>', methods=['GET','POST'])
@supplier_required
def supplier_edit_category(cid):
    db = get_db()
    cat = db.execute('SELECT * FROM category WHERE id=?', (cid,)).fetchone()
    if not cat:
        flash("Категорію не знайдено", "danger")
        return redirect(url_for('supplier_categories'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        try:
            db.execute('UPDATE category SET name=? WHERE id=?', (name, cid))
            db.commit()
            flash("Категорію оновлено", "success")
            return redirect(url_for('supplier_categories'))
        except sqlite3.IntegrityError:
            flash("Категорія з такою назвою вже існує", "danger")
    return render_template('supplier/edit_category.html', category=cat)

@app.route('/supplier/categories/delete/<int:cid>', methods=['POST'])
@supplier_required
def supplier_delete_category(cid):
    db = get_db()
    db.execute('DELETE FROM category WHERE id=?', (cid,))
    db.commit()
    flash("Категорію видалено", "success")
    return redirect(url_for('supplier_categories'))

@app.route('/supplier/orders')
@supplier_required
def supplier_orders():
    db = get_db()
    orders = db.execute('''
      SELECT o.*, p.name AS product_name, u.username AS dropshipper
      FROM "order" o
      JOIN product p ON o.product_id=p.id
      JOIN user u ON o.dropshipper_id=u.id
      WHERE p.supplier_id=?
    ''',(session['user_id'],)).fetchall()
    return render_template('supplier/orders.html', orders=orders)
import random, string
@app.route('/supplier/orders/<int:oid>', methods=['GET','POST'])
@supplier_required
def supplier_order_detail(oid):
    db = get_db()

    # GET: підтягуємо замовлення
    order = db.execute('''
      SELECT o.*, p.name
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE o.id = ? AND p.supplier_id = ?
    ''', (oid, session['user_id'])).fetchone()

    # якщо POST — оновлюємо тільки статус
    if request.method == 'POST':
        new_status = request.form['status']
        db.execute('UPDATE "order" SET status = ? WHERE id = ?', (new_status, oid))
        db.commit()
        flash("Статус оновлено", "success")
        return redirect(url_for('supplier_orders'))

    # При першому GET генеруємо TTN, якщо нема
    if order and not order['tracking_number']:
        import random, string
        ttn = ''.join(random.choices(string.digits, k=14))
        db.execute('UPDATE "order" SET tracking_number = ? WHERE id = ?', (ttn, oid))
        db.commit()
        order = db.execute('''
          SELECT o.*, p.name
          FROM "order" o
          JOIN product p ON o.product_id = p.id
          WHERE o.id = ? AND p.supplier_id = ?
        ''', (oid, session['user_id'])).fetchone()

    return render_template('supplier/order_detail.html', order=order)


@app.route('/supplier/stats')
@supplier_required
def supplier_stats():
    db = get_db()
    supplier_id = session['user_id']
    # Загальний дохід і кількість замовлень
    stats = db.execute('''
      SELECT SUM((p.price - p.discount) * o.quantity) AS revenue,
             SUM(o.quantity) AS total_items,
             COUNT(o.id) AS total_orders
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE p.supplier_id = ?
    ''', (supplier_id,)).fetchone()
    total_revenue = stats['revenue'] or 0
    total_items   = stats['total_items'] or 0
    total_orders  = stats['total_orders'] or 0

    # Дохід за товарами
    rows = db.execute('''
      SELECT p.name,
             SUM((p.price - p.discount) * o.quantity) AS rev
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE p.supplier_id = ?
      GROUP BY p.id
    ''', (supplier_id,)).fetchall()
    labels = [r['name'] for r in rows]
    data   = [round(r['rev'],2) for r in rows]

    return render_template('supplier/stats.html',
        total_revenue=round(total_revenue,2),
        total_items=total_items,
        total_orders=total_orders,
        chart_labels=json.dumps(labels, ensure_ascii=False),
        chart_data=json.dumps(data)
    )

# --- Dropshipper views ---

@app.route('/dropshipper')
@dropshipper_required
def dropshipper_dashboard():
    return render_template('dropshipper/dashboard.html')

@app.route('/dropshipper/products')
@dropshipper_required
def dropshipper_products():
    db = get_db()
    prods = db.execute('''
      SELECT p.*, u.username
      FROM product p
      JOIN user u ON p.supplier_id=u.id
      WHERE p.published=1
    ''').fetchall()
    cats = db.execute('SELECT * FROM category').fetchall()
    return render_template('dropshipper/products.html', products=prods, categories=cats)

@app.route('/dropshipper/order/new/<int:pid>', methods=['GET','POST'])
@dropshipper_required
def dropshipper_order_new(pid):
    db = get_db()
    prod = db.execute('SELECT * FROM product WHERE id=?',(pid,)).fetchone()
    if request.method=='POST':
        f = request.form
        db.execute('''
          INSERT INTO "order"(product_id,dropshipper_id,quantity,recipient_name,address,comment)
          VALUES(?,?,?,?,?,?)
        ''',(pid,session['user_id'],int(f['quantity']),f['recipient'],f['address'],f['comment']))
        db.commit()
        return redirect(url_for('dropshipper_orders'))
    return render_template('dropshipper/order_new.html', product=prod)

@app.route('/dropshipper/orders')
@dropshipper_required
def dropshipper_orders():
    db = get_db()
    orders = db.execute('''
      SELECT o.*, p.name
      FROM "order" o
      JOIN product p ON o.product_id=p.id
      WHERE o.dropshipper_id=?
    ''',(session['user_id'],)).fetchall()
    return render_template('dropshipper/orders.html', orders=orders)

@app.route('/dropshipper/orders/<int:oid>', methods=['GET','POST'])
@dropshipper_required
def dropshipper_order_detail(oid):
    db = get_db()
    order = db.execute('''
      SELECT o.*, p.name, p.price, p.discount
      FROM "order" o
      JOIN product p ON o.product_id=p.id
      WHERE o.id=? AND o.dropshipper_id=?
    ''',(oid,session['user_id'])).fetchone()
    if request.method=='POST':
        db.execute('UPDATE "order" SET paid=1,status="paid" WHERE id=?',(oid,))
        db.commit()
        return redirect(url_for('dropshipper_order_detail', oid=oid))
    return render_template('dropshipper/order_detail.html', order=order)

@app.route('/dropshipper/stats')
@dropshipper_required
def dropshipper_stats():
    db = get_db()
    drop_id = session['user_id']
    # Загальні показники
    stats = db.execute('''
      SELECT SUM((p.price - p.discount) * o.quantity) AS spent,
             COUNT(o.id) AS total_orders
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE o.dropshipper_id = ?
    ''', (drop_id,)).fetchone()
    total_spent  = stats['spent'] or 0
    total_orders = stats['total_orders'] or 0

    # Замовлення по товарах
    rows = db.execute('''
      SELECT p.name,
             SUM(o.quantity) AS qty
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE o.dropshipper_id = ?
      GROUP BY p.id
    ''', (drop_id,)).fetchall()
    labels = [r['name'] for r in rows]
    data   = [r['qty'] for r in rows]

    return render_template('dropshipper/stats.html',
        total_spent=round(total_spent,2),
        total_orders=total_orders,
        chart_labels=json.dumps(labels, ensure_ascii=False),
        chart_data=json.dumps(data)
    )

@app.route('/shop')
def shop():
    db = get_db()
    products = db.execute('SELECT p.*, u.username AS supplier_name '
                          'FROM product p JOIN user u ON p.supplier_id=u.id '
                          'WHERE p.published=1').fetchall()
    return render_template('shop.html', products=products)


@app.route('/pay/<int:oid>', methods=['GET','POST'])
@dropshipper_required
def pay_order(oid):
    db = get_db()
    drop_id = session['user_id']
    order = db.execute('''
      SELECT o.*, p.name, p.price, p.discount
      FROM "order" o
      JOIN product p ON o.product_id = p.id
      WHERE o.id = ? AND o.dropshipper_id = ?
    ''', (oid, drop_id)).fetchone()
    if not order:
        flash("Замовлення не знайдено", "danger")
        return redirect(url_for('dropshipper_orders'))

    if request.method == 'POST':
        db.execute('UPDATE "order" SET paid=1, status="paid" WHERE id=?', (oid,))
        db.commit()
        flash("Платіж успішний!", "success")
        return redirect(url_for('dropshipper_order_detail', oid=oid))

    return render_template('payment.html', order=order)


@app.route('/dropshipper/product/<int:pid>', methods=['GET','POST'])
@dropshipper_required
def dropshipper_product_detail(pid):
    db = get_db()
    prod = db.execute('SELECT p.*, u.username AS supplier_name '
                      'FROM product p JOIN user u ON p.supplier_id=u.id '
                      'WHERE p.id=?',(pid,)).fetchone()
    # збираємо всі фото з папки static/uploads/products/<pid>/*
    upload_dir = os.path.join(app.static_folder, 'uploads', 'products', str(pid))
    images = []
    if os.path.isdir(upload_dir):
        for fname in sorted(os.listdir(upload_dir)):
            if fname.lower().endswith(('.png','jpg','jpeg','gif')):
                images.append(f"uploads/products/{pid}/{fname}")

    reviews = db.execute(
        'SELECT r.rating, r.comment, r.created_at, u.username '
        'FROM review r JOIN user u ON r.user_id=u.id '
        'WHERE r.product_id=? ORDER BY r.created_at DESC',
        (pid,)
    ).fetchall()

    if request.method=='POST':
        rating  = int(request.form['rating'])
        comment = request.form['comment']
        db.execute('INSERT INTO review(user_id,product_id,supplier_id,rating,comment)'
                   ' VALUES(?,?,?,?,?)',
                   (session['user_id'], pid, prod['supplier_id'], rating, comment))
        db.commit()
        return redirect(url_for('dropshipper_product_detail', pid=pid))

    return render_template('dropshipper/product_detail.html',
                           product=prod, images=images, reviews=reviews)

@app.route('/supplier/reviews')
@supplier_required
def supplier_reviews():
    db = get_db()
    revs = db.execute('''
      SELECT r.rating, r.comment, r.created_at,
             u.username AS reviewer, p.name AS product_name
      FROM review r
      JOIN user u ON u.id=r.user_id
      JOIN product p ON p.id=r.product_id
      WHERE r.supplier_id=?
      ORDER BY r.created_at DESC
    ''',(session['user_id'],)).fetchall()
    return render_template('supplier/reviews.html', reviews=revs)
# Додаємо нові маршрути для сторінок у нижньому колонтитулі
@app.route('/terms')
def terms():
    return render_template('terms.html', title='Terms of Service')

@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html', title='Privacy Policy')

@app.route('/sitemap')
def sitemap():
    return render_template('sitemap.html', title='Sitemap')

@app.route('/privacy-choices')
def privacy_choices():
    return render_template('privacy_choices.html', title='Privacy Choices')
if __name__ == '__main__':
    app.run(debug=True)
