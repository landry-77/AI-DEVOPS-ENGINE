FROM node:20-alpine
RUN mkdir /workspace && echo '{}' > /workspace/package.json
RUN npm install -g jest
WORKDIR /workspace
