"""Gera a CA de teste e o certificado do servidor usados no TLS.

Responsável: Fellipe — issue #18.

    python certs/gerar_certificados.py            # CA + certificado do servidor
    python certs/gerar_certificados.py --falsos   # também o certificado do teste negativo (#21)

Arquivos gerados em certs/ (NENHUM vai para o git — ver .gitignore):
    ca.crt          certificado da CA de teste: o CLIENTE confia só nele (contexto_cliente)
    ca.key          chave privada da CA (só serve para assinar o certificado do servidor)
    servidor.crt    certificado do servidor, assinado pela CA, válido para localhost e 127.0.0.1
    servidor.key    chave privada do servidor (fica só com o servidor)

Por que uma CA própria em vez de um único certificado autoassinado?
O cliente valida o servidor como na internet de verdade: confere a assinatura
contra uma CA confiável (ca.crt) e confere o nome/IP pedido contra o SAN do
certificado. Um servidor com certificado de outra origem é recusado (#21).

Usa a biblioteca `cryptography` (pip install cryptography). Se ela não estiver
instalada, tenta o OpenSSL de linha de comando (no Windows vem junto com o Git).
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PASTA = Path(__file__).resolve().parent
PASTA_FALSOS = PASTA / "falsos"
VALIDADE_DIAS = 365
NOMES_DNS = ["localhost"]
IPS = ["127.0.0.1"]


# ===================================================================== cryptography
def _gerar_com_cryptography(destino: Path, nome_ca: str, sans_dns: list[str], sans_ip: list[str]) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    agora = dt.datetime.now(dt.timezone.utc)
    inicio, fim = agora - dt.timedelta(minutes=5), agora + dt.timedelta(days=VALIDADE_DIAS)

    def salvar_chave(chave, caminho: Path):
        caminho.write_bytes(chave.private_bytes(serialization.Encoding.PEM,
                                                serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))

    def nome(cn: str):
        return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Chat SD2 - Unimontes"),
                          x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    # ---- CA
    chave_ca = ec.generate_private_key(ec.SECP256R1())
    cert_ca = (x509.CertificateBuilder()
               .subject_name(nome(nome_ca)).issuer_name(nome(nome_ca))
               .public_key(chave_ca.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(inicio).not_valid_after(fim)
               .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
               .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                            content_commitment=False, key_encipherment=False,
                                            data_encipherment=False, key_agreement=False,
                                            encipher_only=False, decipher_only=False), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave_ca.public_key()), critical=False)
               .sign(chave_ca, hashes.SHA256()))

    # ---- servidor, assinado pela CA
    chave_srv = ec.generate_private_key(ec.SECP256R1())
    sans = [x509.DNSName(d) for d in sans_dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sans_ip]
    cert_srv = (x509.CertificateBuilder()
                .subject_name(nome(sans_dns[0] if sans_dns else sans_ip[0])).issuer_name(cert_ca.subject)
                .public_key(chave_srv.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(inicio).not_valid_after(fim)
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                                             content_commitment=False, data_encipherment=False,
                                             key_agreement=True, key_cert_sign=False, crl_sign=False,
                                             encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave_srv.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(chave_ca.public_key()),
                               critical=False)
                .sign(chave_ca, hashes.SHA256()))

    destino.mkdir(parents=True, exist_ok=True)
    (destino / "ca.crt").write_bytes(cert_ca.public_bytes(serialization.Encoding.PEM))
    salvar_chave(chave_ca, destino / "ca.key")
    (destino / "servidor.crt").write_bytes(cert_srv.public_bytes(serialization.Encoding.PEM))
    salvar_chave(chave_srv, destino / "servidor.key")


# ===================================================================== OpenSSL (alternativa)
def _achar_openssl() -> str | None:
    candidatos = [shutil.which("openssl")]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidatos.append(str(Path(base) / "Git" / "usr" / "bin" / "openssl.exe"))
    return next((c for c in candidatos if c and Path(c).is_file()), None)


def _gerar_com_openssl(openssl: str, destino: Path, nome_ca: str, sans_dns: list[str], sans_ip: list[str]) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    san = ",".join([f"DNS:{d}" for d in sans_dns] + [f"IP:{i}" for i in sans_ip])
    cn = sans_dns[0] if sans_dns else sans_ip[0]
    with tempfile.TemporaryDirectory() as tmp:
        ext_ca = Path(tmp) / "ca.ext"
        ext_ca.write_text("basicConstraints=critical,CA:TRUE,pathlen:0\n"
                          "keyUsage=critical,digitalSignature,keyCertSign,cRLSign\n"
                          "subjectKeyIdentifier=hash\n")
        ext_srv = Path(tmp) / "srv.ext"
        ext_srv.write_text(f"subjectAltName={san}\nbasicConstraints=critical,CA:FALSE\n"
                           "keyUsage=critical,digitalSignature,keyAgreement\nextendedKeyUsage=serverAuth\n"
                           "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n")
        csr = Path(tmp) / "srv.csr"
        d = lambda n: str(destino / n)
        comandos = [
            [openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", d("ca.key")],
            [openssl, "req", "-new", "-x509", "-key", d("ca.key"), "-out", d("ca.crt"), "-days", str(VALIDADE_DIAS),
             "-subj", f"/O=Chat SD2 - Unimontes/CN={nome_ca}", "-extensions", "v3", "-config", str(ext_ca)],
            [openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", d("servidor.key")],
            [openssl, "req", "-new", "-key", d("servidor.key"), "-out", str(csr),
             "-subj", f"/O=Chat SD2 - Unimontes/CN={cn}"],
            [openssl, "x509", "-req", "-in", str(csr), "-CA", d("ca.crt"), "-CAkey", d("ca.key"),
             "-CAcreateserial", "-out", d("servidor.crt"), "-days", str(VALIDADE_DIAS), "-sha256",
             "-extfile", str(ext_srv)],
        ]
        # O "req -x509" lê as extensões de uma seção: monta o arquivo no formato de config.
        ext_ca.write_text("[req]\ndistinguished_name=dn\n[dn]\n[v3]\n" + ext_ca.read_text())
        for cmd in comandos:
            subprocess.run(cmd, check=True, capture_output=True)
    for sobra in destino.glob("*.srl"):
        sobra.unlink()


# ===================================================================== interface
def gerar(destino: Path = PASTA, nome_ca: str = "CA de teste - Chat SD2",
          sans_dns: list[str] | None = None, sans_ip: list[str] | None = None) -> str:
    """Gera ca.crt/ca.key/servidor.crt/servidor.key em `destino`. Devolve a ferramenta usada."""
    sans_dns = NOMES_DNS if sans_dns is None else sans_dns
    sans_ip = IPS if sans_ip is None else sans_ip
    try:
        _gerar_com_cryptography(destino, nome_ca, sans_dns, sans_ip)
        return "cryptography"
    except ImportError:
        openssl = _achar_openssl()
        if openssl is None:
            sys.exit("Instale a biblioteca:  pip install cryptography\n"
                     "(ou instale o Git for Windows, que traz o openssl.exe)")
        _gerar_com_openssl(openssl, destino, nome_ca, sans_dns, sans_ip)
        return f"OpenSSL ({openssl})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os certificados de teste do chat")
    parser.add_argument("--falsos", action="store_true",
                        help="gera também certificados para o teste negativo (#21) em certs/falsos/")
    opcoes = parser.parse_args()

    ferramenta = gerar()
    print(f"Certificados gerados em {PASTA} (com {ferramenta}):")
    for nome in ("ca.crt", "ca.key", "servidor.crt", "servidor.key"):
        print(f"  {nome}")
    print(f"  válidos para: {', '.join(NOMES_DNS + IPS)} por {VALIDADE_DIAS} dias")

    if opcoes.falsos:
        # Certificado de servidor assinado por OUTRA CA, que o cliente não conhece.
        # Uso: python -m servidor --certificado-falso  ->  o cliente TLS deve RECUSAR a conexão.
        gerar(PASTA_FALSOS, nome_ca="CA desconhecida (teste negativo)")
        print(f"\nCertificado falso (outra CA) em {PASTA_FALSOS}")
        print("  Teste: python -m servidor --certificado-falso  e conecte um cliente com TLS.")

    print("\nNunca faça commit dos arquivos .key (o .gitignore já os bloqueia).")


if __name__ == "__main__":
    main()
