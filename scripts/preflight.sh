#!/usr/bin/env bash
# Run before every push. Fails if a secret could be committed.
set -u
fail=0
cd "$(dirname "$0")/.."

if ! grep -qx '\.env' .gitignore; then echo "FAIL: .env is not listed in .gitignore"; fail=1; fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then echo "FAIL: .env is tracked by git"; fail=1; fi
  files=$(git ls-files)
else
  files=$(find . -type f -not -path './.venv/*' -not -path './.git/*' -not -name '.env')
fi

# Real-looking provider keys in tracked files (the fake canary in data/private is allowed).
if echo "$files" | xargs grep -nE 'sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}' 2>/dev/null | grep -v 'data/private/'; then
  echo "FAIL: something that looks like an API key is in a tracked file"; fail=1
fi
if echo "$files" | xargs grep -nE '^(ANTHROPIC|OPENAI)_API_KEY=.+' 2>/dev/null | grep -v '\.env\.example'; then
  echo "FAIL: a filled-in API key line is in a tracked file"; fail=1
fi

if [ "$fail" -eq 0 ]; then echo "preflight ok"; fi
exit $fail
