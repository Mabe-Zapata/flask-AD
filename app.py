from flask import Flask, jsonify, request
from urllib import request as urlrequest
from html import escape
import json
import os
import certifi
import pytds

#===============================
# conexion con la base de datos
#===============================

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    # Set CORS_ORIGIN to the WordPress domain in production; "*" allows any site
    response.headers["Access-Control-Allow-Origin"] = os.environ.get("CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

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

def enviar_correo(proceso, detalle, detalle_html=None):
    # Sends through a Google Apps Script web app over HTTPS (Render free blocks SMTP)
    script_url = os.environ.get("APPS_SCRIPT_URL")
    token = os.environ.get("APPS_SCRIPT_TOKEN")
    destino = os.environ.get("EMAIL_DESTINO")

    faltantes = [
        nombre for nombre, valor in (
            ("APPS_SCRIPT_URL", script_url),
            ("APPS_SCRIPT_TOKEN", token),
            ("EMAIL_DESTINO", destino),
        ) if not valor
    ]
    if faltantes:
        return f"Faltan variables de entorno: {', '.join(faltantes)}"

    payload = json.dumps({
        "token": token,
        "to": destino,
        "subject": f"Proceso: {proceso}",
        "body": detalle,
        "htmlBody": detalle_html,
    }).encode("utf-8")
    req = urlrequest.Request(
        script_url, data=payload, headers={"Content-Type": "application/json"}
    )

    # Returns None on success, or a readable error message
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            texto = resp.read().decode("utf-8")
    except OSError as e:  # URLError and read timeouts both subclass OSError
        app.logger.exception("No se pudo conectar con Apps Script")
        return f"No se pudo conectar con Apps Script: {e}"

    try:
        resultado = json.loads(texto)
    except ValueError:
        # Apps Script answers HTML when the deployment is not public or the URL is wrong
        return "Apps Script no devolvio JSON: revisa que la URL termine en /exec y que el acceso sea 'Cualquier persona'"

    if not resultado.get("ok"):
        return f"Apps Script rechazo el envio: {resultado.get('error')}"
    return None

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

    total = len(rows)
    resumen = f"Registros procesados: {total}"

    # Plain text fallback for mail clients that do not render HTML
    detalle = resumen + "\n\n" + ("\n".join(
        f"ID: {row[0]} | Nombre: {row[1]} | Precio: {row[2]} | Stock: {row[3]}"
        for row in rows
    ) or "No hay productos registrados")

    celda = 'style="border:1px solid #ddd;padding:8px"'
    filas_html = "".join(
        f"<tr><td {celda}>{row[0]}</td><td {celda}>{escape(str(row[1]))}</td>"
        f'<td {celda} align="right">{row[2]}</td><td {celda} align="right">{row[3]}</td></tr>'
        for row in rows
    ) or f'<tr><td {celda} colspan="4">No hay productos registrados</td></tr>'
    detalle_html = f"""
        <div style="font-family:Arial,sans-serif;color:#222">
            <h2 style="margin:0 0 8px">{escape(proceso)}</h2>
            <p style="margin:0 0 16px"><strong>{resumen}</strong></p>
            <table style="border-collapse:collapse;font-size:14px">
                <thead>
                    <tr style="background:#000;color:#fff">
                        <th {celda}>ID</th><th {celda}>Nombre</th>
                        <th {celda}>Precio</th><th {celda}>Stock</th>
                    </tr>
                </thead>
                <tbody>{filas_html}</tbody>
            </table>
        </div>
    """

    error = enviar_correo(proceso, detalle, detalle_html)
    if error:
        return jsonify({"message": "Error al enviar correo", "error": error}), 500

    return jsonify({"message": "Correo enviado con exito", "registros": total}), 200

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