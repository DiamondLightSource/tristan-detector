FROM ghcr.io/odin-detector/odin-data-build:1.12.0 AS developer

FROM developer AS build

RUN python -m pip install opencv-python-headless

# Root of tristan-detector
COPY . /odin/tristan-detector

# C++
WORKDIR /odin/tristan-detector
RUN mkdir -p build && cd build && \
    cmake -DCMAKE_INSTALL_PREFIX=/odin -DODINDATA_ROOT_DIR=/odin ../cpp && \
    make -j8 VERBOSE=1 && \
    make install

# Python
WORKDIR /odin/tristan-detector/python
RUN python -m pip install .

FROM ghcr.io/odin-detector/odin-data-runtime:1.12.0 AS runtime

COPY --from=build /odin /odin
COPY --from=build /venv /venv
COPY deploy /odin/tristan-deploy

RUN rm -rf /odin/tristan-detector

ENV PATH=/odin/bin:/odin/venv/bin:$PATH

WORKDIR /odin

CMD ["sh", "-c", "cd /odin/tristan-deploy && zellij --layout ./layout.kdl"]
