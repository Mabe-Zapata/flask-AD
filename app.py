from flask import Flask, jsonify, request  
import os
import certifi 
import pytds

#La conexion viene del pytds
#==============================
#conexion con la base de datos
#==============================

app = Flask(__name__)

def getConnection():
    return pytds.connect(server=os.environ["DB_SERVER"],
                        database=os.environ["DB_NAME"],
                        user=os.environ['DB_USER'],
                        password=os.environ["DB_PASS"],
                        port=1433,
                        cafile=certifi.where(),
                        validate_host=True,
                        row_strategy=pytds.namedtuple_row_strategy)
    
    ##esto es una mejor practica en un environment, esto lo vamos a llevar a render y el objetivo va a ser que se mejore 
    ## con la config de wordpress me voy a conectar a una api de render dode se trae la info desde el sql.
    
@app.route("/test-db", methods=["GET"])
def test_db():
    try:
        conn = getConnection()
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME()")##igual que en oracle
        database = cursor.fetchone()[0]
        conn.close()
        return jsonify({
            "mensaje": "Conexion exitosa a la base de datos",
            "base_de_datos": database
        }),200 
    except Exception as e:
        return jsonify({
            "mensaje": "Error al conectar a la base de datos",
            "error": str(e)
        }), 500
        
        
##vista de productos)
@app.route("/api/products", methods=["GET"])
def getProducts():
    try:
        conn = getConnection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, names, price, stock, version
            FROM products_vw
        """)

        products = []

        for row in cursor.fetchall():
            products.append({
                "id": row[0],
                "names": row[1],
                "price": row[2],
                "stock": row[3],
                "version": row[4]
            })

        cursor.close()
        conn.close()

        return jsonify(products), 200

    except Exception as e:
        return jsonify({
            "mensaje": "Error al obtener los productos",
            "error": str(e)
        }), 500

 
@app.route("/api/products/<int:id>", methods=["GET"])
def get_product(id):
    try:
        conn = getConnection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, names, price, stock, version
            FROM products_vw
            WHERE id = ?
        """, (id,))

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
            product = {
                "id": row[0],
                "names": row[1],
                "price": row[2],
                "stock": row[3],
                "version": row[4]
            }

            return jsonify(product), 200

        return jsonify({
            "mensaje": "Producto no encontrado"
        }), 404

    except Exception as e:
        return jsonify({
            "mensaje": "Error al obtener el producto",
            "error": str(e)
        }), 500

@app.route("/api/products", methods=["POST"])
def create_product():
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "mensaje": "No existen datos validos"
            }), 400
            
        names = data.get("names")
        price = data.get("price")
        stock = data.get("stock")
        
        if not names or price is None or stock is None:
            return jsonify({
                "mensaje": "Faltan datos requeridos"
            }), 400
            
        conn = getConnection()
        cursor = conn.cursor()
        cursor.execute("""EXEC products_insert_sp ?,?, ?""", names, price, stock)
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensaje": "Producto creado exitosamente"}), 201
    except Exception as e:
        return jsonify({
            "mensaje": "Error al procesar la solicitud",
            "error": str(e)
        }), 500
#############
#UPDATE
### SIN CONTROLES
import time
import threading

product_lock=threading.Lock()

@app.route("/api/products",methods=['PUT'])
def updateProduct():
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "error":"No se puede actualizar sin data"
            }),400
        conn = getConnection()
        cursor = conn.cursor()
        
        time.sleep(5)
        
        cursor.execute("""UPDATE products set names=?,price=?,stock=? WHERE id=?""",
                       data.get('names'),
                       data.get('price'),
                        data.get('stock'),
                        data.get('id'))
        if cursor.rowcount == 0:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({
                "mensaje":"Registro no encontrado"
            }),400
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({
            "mensaje":"Registro actualizado"
        }),200
        
    except Exception as e:
        return jsonify({
            "error":"Error al actualizar",
            "mensaje":str(e)
        }),500
        
#########################################################################################
##### Con controles
@app.route("/api/products/lock",methods=["PUT"])
def update_locks():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"msg":"Falta informacion"}),400
        ##creo este proceso para que finalice y el otro ejecute
        with product_lock:
            print("Entra al bloqueo")
            conn = getConnection()
            cursor = conn.cursor()
            cursor.execute("""UPDATE products set names=?,
                           price=?,stock=? WHERE id=?""",
                       data.get('names'),
                       data.get('price'),
                        data.get('stock'),
                        data.get('id'))
            
            if cursor.rowcount == 0:
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({"msg":"Registro no encontrado"}),404
            conn.commit()
            cursor.close()
            conn.close()
                          
            print("Sale del bloqueo")
            
            return jsonify({"msg":"Registro actualizado todo OK"}),200
            
    except Exception as e:
        return jsonify({"msg":"Error al actualizar", "error":str(e)}),500

@app.route("/api/products/version",methods=["PUT"])
def update_version():
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "msg":"No hay datos completos"
            }),400
        if data.get("version") is None:
            return jsonify({
                            "msg":"Faltan parametros (version)"
                        }),400
        conn = getConnection()
        cursor = conn.cursor()
        
        cursor.execute("""UPDATE products set names=?,
                           price=?,stock=?, version = version + 1 WHERE id=? and version=?""",
                       data.get('names'),
                       data.get('price'),
                        data.get('stock'),
                        data.get('id'),
                        data.get('version'))
        if cursor.rowcount == 0:
            cursor.execute("select version from products where id = ?",data.get("id"))
            row=cursor.fetchone()
            conn.rollback()
            cursor.close()
            conn.close()
            if row:
               producto_actual = {
                    "id": data.get("id"),
                    "version": row[0]
                    } 
            return jsonify({"msg":"Ya actualizaron este registro", "error": producto_actual}),404
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({
            "msg":"Producto actualizado con exito"
        }),200
        
    except Exception as e:
        return jsonify({"msg":"Error al actualizar", "error":str(e)}),500
        
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True) #aqui se ejecuta la aplicacion flask, 
    #debug=True para que se reinicie automaticamente al hacer cambios