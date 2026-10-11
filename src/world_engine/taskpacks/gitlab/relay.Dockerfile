FROM python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
COPY relay.py /relay/relay.py
USER 65534:65534
ENTRYPOINT ["python", "-I", "/relay/relay.py"]
