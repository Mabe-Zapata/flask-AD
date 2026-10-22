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

    
    
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            texto = resp.read().decode("utf-8")
    except OSError as e:  
        app.logger.exception("No se pudo conectar con Apps Script")
        return f"No se pudo conectar con Apps Script: {e}"

    try:
        resultado = json.loads(texto)
    except ValueError:
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

    detalle = resumen + "\n\n" + ("\n".join(
        f"ID: {row[0]} | Nombre: {row[1]} | Precio: {row[2]} | Stock: {row[3]}"
        for row in rows
    ) or "No hay productos registrados")

    celda = 'padding:12px 14px;border-bottom:1px solid #e8e8ee'
    encabezado = 'padding:12px 14px;font-size:12px;letter-spacing:1px;text-transform:uppercase'

    def fila_html(i, row):
        fondo = "#ffffff" if i % 2 == 0 else "#f6f7fb"
        stock = row[3]
        color_stock = "#c0392b" if stock is not None and stock <= 5 else "#1e8449"
        return (
            f'<tr style="background:{fondo}">'
            f'<td style="{celda};color:#888">#{row[0]}</td>'
            f'<td style="{celda};font-weight:bold">{escape(str(row[1]))}</td>'
            f'<td style="{celda};color:#4f46e5;font-weight:bold" align="right">${row[2]}</td>'
            f'<td style="{celda};color:{color_stock};font-weight:bold" align="right">{stock}</td>'
            '</tr>'
        )

    filas_html = "".join(fila_html(i, row) for i, row in enumerate(rows)) or (
        f'<tr><td style="{celda};text-align:center;color:#888" colspan="4">'
        'No hay productos registrados</td></tr>'
    )
    detalle_html = f"""
        <div style="background:#eef0f7;padding:32px 12px;font-family:Arial,sans-serif;color:#222">
            <table align="center" width="600" cellpadding="0" cellspacing="0"
                   style="margin:0 auto;width:100%;max-width:600px;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.08)">
                <tr>
                    <td align="center" style="background:#4f46e5;padding:32px 24px;color:#fff">
                        <div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;opacity:.8">Catalogo de productos</div>
                        <h1 style="margin:8px 0 0;font-size:26px">{escape(proceso)}</h1>
                        <div style="margin-top:12px;display:inline-block;background:rgba(255,255,255,.2);border-radius:20px;padding:6px 16px;font-size:13px">{resumen}</div>
                    </td>
                </tr>
                <tr>
                    <td style="padding:24px">
                        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;border:1px solid #e8e8ee">
                            <thead>
                                <tr style="background:#1f2937;color:#fff">
                                    <th align="left" style="{encabezado}">ID</th>
                                    <th align="left" style="{encabezado}">Producto</th>
                                    <th align="right" style="{encabezado}">Precio</th>
                                    <th align="right" style="{encabezado}">Stock</th>
                                </tr>
                            </thead>
                            <tbody>{filas_html}</tbody>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td align="center" style="padding:16px;background:#f6f7fb;font-size:12px;color:#888">
                        Stock en rojo: 5 unidades o menos
                    </td>
                </tr>
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