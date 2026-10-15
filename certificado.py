"""Certificado HTTPS para rodar o FrequencyON na rede local.

Cria uma autoridade certificadora (CA) própria do projeto e, com ela, o certificado do servidor
para localhost e os IPs desta máquina. Instale o arquivo instance/ca-frequencyon.pem uma vez em
cada computador (ou celular) para o navegador confiar no site sem o aviso de "não seguro".
O certificado do servidor é refeito sozinho quando vence ou quando o IP da máquina muda.
"""
import datetime
import ipaddress
import os
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _agora():
    return datetime.datetime.now(datetime.timezone.utc)


def ips_da_maquina():
    ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))           # não envia nada; só descobre o IP da rede
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(ips)


def _salvar(caminho, dados):
    with open(caminho, "wb") as f:
        f.write(dados)


def _chave_pem(chave):
    return chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                               serialization.NoEncryption())


def _ca(pasta):
    """Carrega a CA do projeto ou cria uma nova (vale 10 anos)."""
    cert_path, chave_path = os.path.join(pasta, "ca-frequencyon.pem"), os.path.join(pasta, "ca-frequencyon.key")
    if os.path.exists(cert_path) and os.path.exists(chave_path):
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        with open(chave_path, "rb") as f:
            chave = serialization.load_pem_private_key(f.read(), password=None)
        if cert.not_valid_after_utc > _agora() + datetime.timedelta(days=30):
            return cert, chave

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FrequencyON"),
                      x509.NameAttribute(NameOID.COMMON_NAME, f"FrequencyON CA local ({socket.gethostname()})")])
    cert = (x509.CertificateBuilder()
            .subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_agora() - datetime.timedelta(minutes=5))
            .not_valid_after(_agora() + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
            # a CA só assina endereços locais: se a chave vazar, não serve para falsificar outros sites
            .add_extension(x509.NameConstraints(permitted_subtrees=[
                x509.DNSName("localhost"), x509.DNSName(socket.gethostname()),
                x509.IPAddress(ipaddress.ip_network("127.0.0.0/8")),
                x509.IPAddress(ipaddress.ip_network("10.0.0.0/8")),
                x509.IPAddress(ipaddress.ip_network("172.16.0.0/12")),
                x509.IPAddress(ipaddress.ip_network("192.168.0.0/16")),
            ], excluded_subtrees=None), critical=True)
            .sign(chave, hashes.SHA256()))
    _salvar(chave_path, _chave_pem(chave))
    _salvar(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    print(f"[https] autoridade certificadora criada: {cert_path}")
    return cert, chave


def _precisa_refazer(cert_path, ips):
    if not os.path.exists(cert_path):
        return True
    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    if cert.not_valid_after_utc < _agora() + datetime.timedelta(days=30):
        return True
    nomes = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    ips_cert = {str(i) for i in nomes.get_values_for_type(x509.IPAddress)}
    return not set(ips) <= ips_cert


def certificado_local(pasta):
    """Devolve (certificado, chave) do servidor, criando ou renovando quando preciso."""
    os.makedirs(pasta, exist_ok=True)
    cert_path, chave_path = os.path.join(pasta, "servidor.pem"), os.path.join(pasta, "servidor.key")
    ips = ips_da_maquina()
    ca_cert, ca_chave = _ca(pasta)
    if not _precisa_refazer(cert_path, ips) and os.path.exists(chave_path):
        return cert_path, chave_path

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host = socket.gethostname()
    nomes = [x509.DNSName("localhost"), x509.DNSName(host)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
            .issuer_name(ca_cert.subject)
            .public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_agora() - datetime.timedelta(minutes=5))
            .not_valid_after(_agora() + datetime.timedelta(days=397))   # limite aceito pelos navegadores
            .add_extension(x509.SubjectAlternativeName(nomes), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_chave.public_key()), critical=False)
            .sign(ca_chave, hashes.SHA256()))
    _salvar(chave_path, _chave_pem(chave))
    _salvar(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    print(f"[https] certificado do servidor criado para: localhost, {host}, {', '.join(ips)}")
    return cert_path, chave_path
