# HLdemStego

Esteganografia en demos GoldSrc (Half-Life / Counter-Strike 1.6).
Oculta archivos dentro de archivos .dem usando solo la biblioteca estandar de Python.

---

## Que hace

Agarra cualquier archivo (texto, imagen, binario) y lo oculta dentro de un .dem del motor GoldSrc.
La demo modificada se puede reproducir normalmente en el juego.
El archivo oculto solo se puede recuperar con HLdemStego + la demo original.

---

## Modelo de seguridad

```
archivo --> zlib --> [XOR keystream HMAC-SHA256] --> base64 --> chunks barajados --> .dem
```

**La clave se deriva de los movimientos del jugador en la demo:**

Cada frame "CLIENTDATA" contiene timestamp, posicion XYZ, angulos de vista y
estado de armas. HLdemStego hace un SHA-256 de TODOS esos datos en orden temporal.
El resultado es la "huella criptografica" de esa partida especifica.

- **Alterar un solo fotograma** (un angulo de vista en 0.001 grados) cambia
  completamente la clave y hace el archivo irrecuperable.
- **Sin el stego.dem**: no hay chunks.
- **Con el stego.dem pero sin la demo correcta**: los chunks son ruido.
- **Con password**: se aplica PBKDF2-HMAC-SHA256 (200.000 iteraciones) con
  el hash de la demo como sal. Necesitas AMBOS para descifrar.

**Autenticacion**: HMAC-SHA256 del ciphertext completo (Encrypt-then-MAC).
Cualquier modificacion del .dem es detectada antes de descomprimir.

**Shuffle**: Fisher-Yates con HMAC-CSPRNG (no Mersenne Twister). Sin la clave
es imposible predecir el orden de los fragmentos.

---

## Instalacion

Solo Python 3.9+. Sin dependencias externas.

```
git clone https://github.com/sapyOMG/HLdemStego.git
cd HLdemStego
```

---

## Uso

### Windows
Doble clic en `ABRIR.cmd` para el menu interactivo de PowerShell.
O en la barra de direcciones de la carpeta "HLdemStego" ponér: `powershell -ExecutionPolicy Bypass -File hldemstego.ps1`

### Linea de comandos

```bash
# Ver cuanto tiene que durar la demo para tu archivo
python calcular.py secreto.txt

# Cifrar (clave = movimientos del jugador en la demo)
python -m hldemstego encode secreto.txt mi_demo.dem salida.dem

# Cifrar con password adicional (mas seguro)
python -m hldemstego encode secreto.txt mi_demo.dem salida.dem --password mipass

# Descifrar
python -m hldemstego decode salida.dem ./recuperado/

# Descifrar con password
python -m hldemstego decode salida.dem ./recuperado/ --password mipass

# Verificar tokens DC:* en el .dem
python -m hldemstego inspect salida.dem
```

---

## Arquitectura

```
HLdemStego/
  hldemstego/
    constants.py      Constantes del formato GoldSrc
    dem_io.py         Parser/serializer binario del .dem
    cryptocore.py     Cifrado HMAC-SHA256-CTR, CSPRNG, PBKDF2, HMAC, path-traversal
    input_handler.py  Compresion + cifrado + fragmentacion
    entropy.py        Recoleccion CLIENTDATA + derivacion de clave
    stego.py          Inyeccion/extraccion con MAC en DC:END
    pipeline.py       Orquestacion encode/decode/inspect
    __main__.py       CLI
  tests/              32 tests unitarios
  calcular.py         Calcula cuanto .dem necesitas para tu archivo
  ABRIR.cmd           Lanzador Windows (abre el PS1)
  hldemstego.ps1       Menu interactivo PowerShell
```

---

## Tests

```bash
python -m unittest discover tests/ -v
# 32 tests - incluyendo: cifrado/descifrado, clave incorrecta falla,
# MAC tampered falla, path traversal bloqueado, limites DoS, pipeline e2e
```

---

## Librerias usadas

`struct`, `base64`, `zlib`, `hashlib`, `hmac`, `os`, `secrets`, `re`,
`argparse`, `unittest` - 100% biblioteca estandar de Python.

---

## Uso de IA

Claude (Sonnet 4.6):
- Crear el programa
- Parchear  vulnerabilidades encontradas

---

## Licencia

MIT
