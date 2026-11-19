FROM apify/actor-python:3.12

COPY requirements.txt ./

RUN echo "Python version:" \
 && python --version \
 && echo "Pip version:" \
 && pip --version \
 && echo "Installing dependencies:" \
 && pip install -r requirements.txt \
 && echo "All installed Python packages:" \
 && pip freeze

# Only the Actor code goes into the image (no tests, fixtures, scripts or notes).
COPY src ./src

RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
