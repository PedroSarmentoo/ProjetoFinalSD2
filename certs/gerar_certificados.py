"""Gera a CA de teste e o certificado do servidor usados no TLS.

Responsável: Fellipe — issue #18.
Saída em certs/: ca.crt, ca.key, servidor.crt, servidor.key
SAN: DNS:localhost, IP:127.0.0.1 (demonstração em um único PC — #29).
As chaves privadas (*.key) NUNCA vão para o git (.gitignore).

Uso: python certs/gerar_certificados.py
"""

import sys

if __name__ == "__main__":
    sys.exit("[esqueleto] geração de certificados ainda não implementada: issue #18 (Fellipe)")
