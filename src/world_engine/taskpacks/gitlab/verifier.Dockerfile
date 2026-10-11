ARG BASE_IMAGE=python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
FROM ${BASE_IMAGE}
COPY verify.py /grader/verify.py
USER 65534:65534
ENTRYPOINT ["python", "-I", "/grader/verify.py"]
