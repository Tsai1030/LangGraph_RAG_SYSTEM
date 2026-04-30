module.exports = {
  apps: [
    {
      name: "backend",
      cwd: "C:/Users/226376/Desktop/data/backend",
      script: "uv",
      args: "run uvicorn app.main:app --host 0.0.0.0 --port 8000",
      interpreter: "none",
    },
    {
      name: "frontend",
      cwd: "C:/Users/226376/Desktop/data/frontend",
      script: "node_modules/next/dist/bin/next",
      args: "start -H 0.0.0.0 -p 3000",
      interpreter: "node",
    },
  ],
};
