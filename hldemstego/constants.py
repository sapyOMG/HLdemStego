"""
Constantes del formato binario GoldSrc .dem y configuracion de HLdemStego.
"""
import struct

# --- Firma y header ------------------------------------------------------------
DEMO_MAGIC      = b"HLDEMO\x00\x00"
HEADER_SIZE     = 544
DIR_ENTRY_SIZE  = 92

# --- Frame header --------------------------------------------------------------
FRAME_HDR_FMT   = "<fB"
FRAME_HDR_SIZE  = struct.calcsize(FRAME_HDR_FMT)   # 5 bytes

# --- Tipos de frame ------------------------------------------------------------
FRAME_UNKNOWN    = 0
FRAME_STARTUP    = 1
FRAME_NORMAL     = 2   # NET_MSG  ? usamos este para inyectar chat visible
FRAME_STRINGCMD  = 3   # comando consola (fallback / extraccion legacy)
FRAME_LASTRECORD = 4
FRAME_EVENT      = 5
FRAME_SOUND      = 6
FRAME_BUFFER     = 7
FRAME_CLIENTDATA = 8
FRAME_WEAPONANIM = 9

# --- Tamanos fijos de body -----------------------------------------------------
FRAME_BODY_SIZES = {
    FRAME_UNKNOWN:    0,
    FRAME_LASTRECORD: 0,
    FRAME_EVENT:      84,
    FRAME_WEAPONANIM: 8,
    FRAME_CLIENTDATA: 32,
}

# --- NET_MSG democmdinfo -------------------------------------------------------
DEMOCMDINFO_SIZE = 164

# --- Mensajes SVC de GoldSrc --------------------------------------------------
SVC_PRINT       = 8    # imprime texto en HUD (notificaciones top-left) y consola
SVC_CENTERPRINT = 26   # texto centrado en pantalla (muy visible)
SVC_STUFFTEXT   = 9    # ejecuta comando en el cliente

# --- Configuracion de HLdemStego ------------------------------------------------
CHUNK_SIZE       = 80
MIN_INJECT_GAP   = 0.05   # segundos entre frames inyectados

# Tokens de protocolo (sin prefijo "say " - los frames NET_MSG no lo necesitan)
DC_HEAD_TOKEN  = "HL:HEAD"
DC_END_TOKEN   = "HL:END"
DC_DATA_PREFIX = "HL:"

# --- Entropia -----------------------------------------------------------------
JUMP_Z_DELTA  = 2.5
FIRE_BITS_MASK = 0x01
