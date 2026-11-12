# TODO

## Stage 5: convert tool calls

- **Results that every format accepts.** A few result formats take any text as a plain result, e.g. Claude Code `Bash` output, so an unexpected result there can never become `unknown_format`. Decide whether to mark these formats in the tool catalog, and whether each audit should report the common first lines inside them.
- **Missing Claude Code exit codes.** Claude Code writes `Exit code N` only when it judges a result an error, so `grep` that exits 1 has no header. The structured result keeps it in `returnCodeInterpretation`. Check why many calls have no exit code, and whether the structured result can fill it.
- **Codex `exec` steps.** One `exec` script has one result for all its steps. Decide whether to split the output per step when a script has one step that prints its own result, how to count steps inside loops and conditions, how to resolve `web__run` turn references such as `turn0view0` to URLs, and what to do with runtime session ids.

## Stage 8: expand calls

- **Files changed by commands the code does not recognize.** After a write tool writes f.sh, `curl -o f.sh u` replaces it, but `bash f.sh` still runs the earlier content. In the data, the programs that name a file between its write and its run mostly run it (bash, sh, `source`), make it executable (`chmod`), read it (cat, grep, head) or match its name (pgrep, pkill), and writers the code does not know are rare. A fix could make the content unknown after any other program that names the file.
- **Values of a variable assigned twice in sequence.** `U=a; curl $U; U=b; curl $U` gives the second curl both a and b, though it can only see b. Fixing it needs the branches each assignment runs in, e.g. inside `if` or after `&&`.

## Stage 9: candidate requests

- **Default values in `${NAME:-default}`.** `curl ${U:-https://b.org}` gives the host `b.org}`, which counts as templated. Decide whether to fill in the default when the value is unknown, or keep the whole expansion unknown.

## Stage 11: link requests to observations

- **Exit codes at the end of background output files.** When a later call reads a Claude Code background output file, its last line can be `[exited with code N]`. Read it as the exit code of the background command.
- **Effects seen in later calls.** A later `import requests` that works, or a read of a downloaded file, can show that an earlier request succeeded. Decide whether such effects count as evidence.

## Stages 11 and 12: judgment rules to settle

Each rule changes how far some requests count as having got. Settle each one and write it down before stages 11 and 12 are built.

| Rule | Example |
|---|---|
| Which command a result line belongs to when several commands of a call print | `cd x && curl u \| tail -1` |
| Whether a loop counts once per value or once | `for p in a b; do pip install $p; done` |
| Whether `a \|\| b` is judged by the exit code | b in `pip install x \|\| pip install y` |
| Whether curl exit 0 counts as the server answering | `curl -s u` with exit 0 and no other line |
| Whether pip's new version notice counts as reaching the index | `[notice] A new release of pip is available` |
| Whether a HEAD response counts as reaching the server | `curl -I u`, `wget --spider u`, `git push` |

## Stage 12: decide how far each request got

- **Web search that runs on the provider's servers.** Codex web search runs on OpenAI's servers, and the trajectory keeps the query but not the result. Decide how to count a request made outside the agent's container, and which level to grant without result text.
- **Subagent calls outside Muse.** Only Muse keeps the calls inside a subagent. Elsewhere only the launch call and its result remain. Decide whether to report subagent internet use for those harnesses as a lower bound. Devin `read_subagent` reads a subagent's result but is labeled `OtherAction` in the tool catalog.
