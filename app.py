from flask import Flask, jsonify, request
from email.mime.text import MIMEText
from smtplib import SMTP_SSL
import os
import certifi
import pytds

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

#===============================
# conexion con la base de datos
#===============================

app = Flask(__name__)

def getConnection():
    return pytds.connect(
        server=os.environ.get("DB_SERVER"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        database=os.environ.get("DB_NAME"),
        port=1433,
        cafile=certifi.where(),
        validate_host=True,
        row_strategy=pytds.namedtuple_row_strategy
    )

def enviar_correo(proceso, detalle):
    remitente = os.environ.get("EMAIL_REMITENTE")
    password = os.environ.get("GMAIL_APP_PASSWORD")  # Gmail app password (16 chars)
    destino = os.environ.get("EMAIL_DESTINO")

    mensaje = MIMEText(detalle, "plain", "utf-8")
    mensaje["Subject"] = f"Proceso: {proceso}"
    mensaje["From"] = remitente
    mensaje["To"] = destino

    try:
        with SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(remitente, password)
            server.sendmail(remitente, [destino], mensaje.as_string())
        return True
    except Exception:
        app.logger.exception("Error al enviar correo")
        return False

@app.route('/api/procesar', methods=['POST'])
def procesar():
    data = request.get_json(silent=True) or {}
    proceso = data.get('proceso')

    if not proceso:
        return jsonify({"message": "Faltan datos requeridos"}), 400

    try:
        with getConnection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, names, price, stock
                    FROM PRODUCTS_VW
                """)
                rows = cursor.fetchall()
    except Exception:
        app.logger.exception("Error al consultar productos")
        return jsonify({"message": "Error interno al consultar productos"}), 500

    detalle = "\n".join(
        f"ID: {row[0]} | Nombre: {row[1]} | Precio: {row[2]} | Stock: {row[3]}"
        for row in rows
    ) or "No hay productos registrados"

    if not enviar_correo(proceso, detalle):
        return jsonify({"message": "Error al enviar correo"}), 500

    return jsonify({"message": "Correo enviado con exito"}), 200

@app.route('/test-db',methods=['GET'])
def test_db():
    try:
        conn = getConnection()
        cursor = conn.cursor()

        cursor.execute("SELECT DB_NAME()")
        database = cursor.fetchone()[0]
        conn.close()
        return jsonify(
            {
                "message":"Conexion exitosa",
                "base_datos":database
            }
        ),200
    except Exception as e:
        return jsonify(
            {
                "message":"Error",
                "error":str(e)
            }
        ), 500

@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        with getConnection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, names, price, stock
                    FROM PRODUCTS_VW
                """)

                products = []

                for row in cursor.fetchall():
                    products.append({
                        "id": row[0],
                        "names": row[1],
                        "price": row[2],
                        "stock": row[3]
                    })

        return jsonify(products), 200

    except Exception:
        app.logger.exception("Error al consultar productos")

        return jsonify({
            "message": "Error interno al consultar productos"
        }), 500

@app.route('/api/products/<int:id>', methods=['GET'])
def get_product(id):
    try:
        with getConnection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, names, price, stock
                    FROM PRODUCTS_VW
                    WHERE id = ?
                """, (id,))

                row = cursor.fetchone()

        if row is None:
            return jsonify({
                "message": "Producto no encontrado"
            }), 404

        product = {
            "id": row[0],
            "names": row[1],
            "price": row[2],
            "stock": row[3]
        }

        return jsonify(product), 200

    except Exception:
        app.logger.exception(
            "Error al consultar el producto %s", id
        )

        return jsonify({
            "message": "Error interno al consultar el producto"
        }), 500

@app.route('/api/products', methods=['POST'])
def create_product():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"message": "No existen datos validos"}), 400

        names = data.get('names')
        price = data.get('price')
        stock = data.get('stock')

        if not names or price is None or stock is None:
            return jsonify({"message": "Faltan datos requeridos"}), 400
        
        conn = getConnection()
        cursor = conn.cursor()

        cursor.execute("""
            EXEC products_insert_sp ?, ?, ?
        """, (names , price, stock))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"message": "Producto creado exitosamente"}), 201
    except Exception as e:
        return jsonify(
            {
                "message": "Error",
                "error": str(e)
            }
        ), 500
        

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)