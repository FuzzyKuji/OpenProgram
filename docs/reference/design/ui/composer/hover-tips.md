# Hover tips in the composer

Every control in the composer area (the environment row above the input
and the control row below it) explains itself on hover with the same
tooltip, `HoverTip` from `components/ui/tooltip.tsx`, never the browser's
native `title` bubble. The tip body is `TipBody`:

- **Title line**: what the control is and its current value, for example
  "Project: fzkuji.github.io", "Permissions: Auto mode", "Thinking
  effort: Medium", "Chat Agent: deepseek-flash".
- **Detail line** (muted, optional): the specifics a chip cannot fit, such
  as a full path, the full branch name and change counts, or what a click
  does ("Click to turn off.").

The tip appears after the pointer rests for 1.5 s, never while the control's own menu is open,
and is wider than the chip (up to Nova's `max-w-xs`, paths wrap anywhere).
It is shadcn's radix-nova tooltip: an inverted badge (foreground on
background) with an arrow, 12px text.

| Control | Title | Detail |
|---|---|---|
| Channel (Local) | Channel: <name> | where the conversation runs; click to switch |
| Project segment | Project: <name> | folder path; fixed for this conversation, or click to choose |
| Working-folder segment | Working folder: <name> | full path; the agent can read and edit it |
| ✕ on a working folder | Remove from this conversation | files on disk stay |
| Git segment | <repo> · <full branch> | uncommitted files and +/−; worktree path; what the menu offers |
| Add folder | Add working folder | give the agent another folder |
| Web page chip | Web page: <title> | the agent can read and operate it; click to close the floating preview, or to bring it back once closed |
| Goal chip | Goal | the goal text; click for progress and controls |
| Permission badge | Permissions: <mode> | the mode's description |
| Options (+) | Options | attach files, toggle tools / web search / sandbox |
| Tool chips | Tools / Web search / Sandbox / Unattended on | what it does; click to turn off |
| Effort | Thinking effort: <level> | how long the model thinks; click to adjust |
| `?` in the effort card | Thinking effort | how long the model reasons; higher levels think longer and use more tokens, lower levels answer faster; Recommended marks the model's default ([effort-picker.html](effort-picker.html)) |
| Model badge | Model: <model> | its role; click to change model |
| Agent badge | Agent: <name> | the configuration the conversation runs with, or that it is always on; click to change Agent |

## Web page preview header

The floating page preview over chat (`components/center-tabs/pip/web-tab-pip.tsx`)
uses the same `HoverTip` + `TipBody` on its header buttons. The eight
resize handles keep their `aria-label`s but show no tip: a bubble popping
up over the page while the pointer skims the edge is noise. The title and
status text are labels, not controls; they keep a native `title` with the
full text for when they truncate.

| Control | Title | Detail |
|---|---|---|
| Open page | Open page | Switch to this tab in the centre |
| Review request (while the agent waits for approval) | Review request | The agent is waiting for your confirmation |
| More (⋮) | More | Auto-follow, action markers and operation history |
| Close (✕) | Close preview | Hides the preview; the agent keeps working |

## Implementation status

- All rows above: **implemented**.
- The send button keeps the native `title`: it is disabled exactly when its
  message matters most (paste lost, attachment loading), and a disabled
  button fires no pointer events for `HoverTip`. **Not migrated.**
- The Fast toggle keeps its existing hint text. **Unchanged by request.**
