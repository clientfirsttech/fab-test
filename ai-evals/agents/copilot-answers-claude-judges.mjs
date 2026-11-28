#!/usr/bin/env node
// riteway agent for `--agent-config ai-evals/agents/copilot.agent-config.json`.
//
// riteway sends three kinds of prompt to one agent: test extraction, the answer under test, and the judge.
// Only the answer should come from GitHub Copilot. Extraction and judging stay on Claude Code, so a Copilot run
// is scored by the same judge as a Claude run and the two pass rates compare.
//
// Copilot CLI runs from npm (@github/copilot, pinned below) by path, not through npx: on Windows npx is a .cmd,
// which needs a shell, and cmd.exe caps a command line at 8K characters. Fetch it once with
//   npx -y @github/copilot@1.0.114 --version
// or point COPILOT_CLI at its npm-loader.js.
import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const COPILOT_VERSION = "1.0.114";
const ANSWER_PROMPT = "You are an AI assistant. Execute the following prompt";
// Neither agent may read a .env: the repository's holds a service principal, and what an agent reads goes to its model.
const CLAUDE_ARGS = ["--disallowedTools", "Read(**/.env)", "Read(**/.env.*)", "-p", "--output-format", "json",
  "--no-session-persistence"];
const prompt = process.argv.at(-1) ?? "";

function copilotCli() {
  if (process.env.COPILOT_CLI) return process.env.COPILOT_CLI;
  const cache = join(process.env.LOCALAPPDATA ?? join(process.env.HOME ?? "", ".npm"), "npm-cache", "_npx");
  for (const entry of existsSync(cache) ? readdirSync(cache) : []) {
    const pkg = join(cache, entry, "node_modules", "@github", "copilot");
    try {
      if (JSON.parse(readFileSync(join(pkg, "package.json"), "utf8")).version === COPILOT_VERSION) {
        return join(pkg, "npm-loader.js");
      }
    } catch { /* not this one */ }
  }
  process.stderr.write(`Copilot CLI ${COPILOT_VERSION} not found: run \`npx -y @github/copilot@${COPILOT_VERSION} --version\` once, or set COPILOT_CLI.\n`);
  process.exit(127);
}

function run(command, args, wrap) {
  const child = spawn(command, args, { stdio: ["ignore", "pipe", "inherit"] });
  let out = "";
  child.stdout.on("data", (chunk) => { out += chunk; });
  child.on("error", (error) => { process.stderr.write(`${command}: ${error.message}\n`); process.exit(127); });
  child.on("close", (code) => {
    process.stdout.write(wrap ? wrap(out) : out);
    process.exit(code ?? 1);
  });
}

if (prompt.startsWith(ANSWER_PROMPT)) {
  // Read-only, as the evals ask: no shell, no file writes, no .env, no question form, no self-update.
  run(process.execPath, [copilotCli(), "-s", "--no-ask-user", "--no-auto-update", "--log-level", "none",
    "--deny-tool", "shell", "--deny-tool", "write", "--deny-tool", "read(.env)", "--deny-tool", "read(.env.*)",
    "-p", prompt],
  (text) => JSON.stringify({ type: "result", result: text.trim() }));
} else {
  run("claude", [...CLAUDE_ARGS, prompt]);
}
