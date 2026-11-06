# Desktop App and built-in browser

All pages, including Settings and sidebar management pages, open in the selected tab. Its name follows the current page, and Back/Forward restores that tab's route and name. Switching tabs restores each tab's current page; visiting a page does not rename the conversation.


Local App refresh preserves permissions of unpacked native dependencies and restores execute permission on the node-pty terminal helper when an earlier refresh removed it.

Each tab keeps its own Back and Forward history, beginning with its default launcher. Navigation restores pages only inside the selected tab; switching tabs adds no history. Opening the same destination from another launcher preserves both tabs independently. Choosing a new destination after Back replaces only that tab’s forward history. History is saved with the tab. Browser controls handle navigation between webpage URLs.

The macOS and Windows Desktop Apps present OpenProgram as a multi-pane workspace. Each pane can hold Files, a chat, the built-in Browser, or a Terminal, and panes can be split or moved between app windows without changing the underlying session or browser tab.

Drag a tab down out of the tab strip, or drag a pane's ••• handle, and the center area turns into a window overview like Mission Control (the dragged tab opens into a small window showing its content, and is left out of the overview since it is in your hand; its place in the tab strip closes and the tabs after it slide over, and dragging back into the strip opens it again): every window becomes a card showing how it last looked, and a split window keeps its split in its card. Drop on the left or right quarter of a card to put the tab beside that window, or on the upper or lower half of its middle to put it above or below; the highlighted half and the hint name where it goes. The window you dropped on grows out of its card to fill the center area, and makes room as it grows: its panes narrow while the tab you dropped slides in beside them, the edge between them moving as one, all on the live window rather than a picture. In the tab strip the merged window keeps its place, and its name changes to the tab you dropped with a short rise. While you drag, the other cards keep their size and leave a gap where the tab would stand on its own, moving aside as the gap follows the pointer. Drop on the gap or on empty space to open the tab on its own there: the overview stays open, with the tab as a card of its own in that place, and the tab strip takes the same order. Drop outside the App window to open it in a new window, or press Escape to cancel. To see all windows without dragging, click the grid button beside the main menu at the right end of the tab strip, or pinch in on the center area with two fingers (on a web page, pinching in at its normal size opens it, and pinching out magnifies the page as in Safari); click a card to switch to it, and press Escape or pinch out to close. As in Mission Control, the cards themselves can be dragged: drop a card on another card's side to merge the two windows, drop it on empty space to move it to the gap the other cards make for it, or drag one pane out of a split card and drop it on empty space to give it a window of its own. The overview looks the same whether it opened from a drag or from the button. Point at a pane's ••• handle and it turns into the macOS window buttons: red closes the tab, yellow moves the pane back to the tab strip, and green opens the tab on its own. Each one animates as on macOS: a closed pane fades away while the others grow into its space, a pane moved to the tab strip bends like the macOS genie and pours up into the bottom edge of its tab, which lights up once as it takes the pane in (a pane leaving a split first gets its tab, which grows out in the strip before the pane folds into it), and green grows the pane to fill the window; tiling and Fill slide the panes into place the same way. With Reduce Motion turned on, layouts change at once. Rest on green to unfold the tiling menu: **Move and resize** (halves; hold Option for quarters), **Fill and arrange** (Fill, left and right, left and stacked right, quarters), **Return to previous layout**, **Equalize sizes** and **More layouts** (top and bottom, single, 9, 16 and saved layouts). On macOS, Control+Option+arrow keys move the focused pane to a half, adding Shift arranges two panes side by side or stacked, Control+Option+F toggles Fill, and Control+Option+R returns to the previous layout. Dividers stick at a third, a half and two thirds, and stop before a pane gets too small to use.

Closing the last tab leaves both the tab bar and center content area empty. No tab or launcher is created automatically. Use the plus button to open a new tab.

The Back and Forward buttons also include the initial New tab page. After opening an application or built-in page from it, use Back to return to the initial page and Forward to restore the destination in the same tab. Choosing another destination after going back replaces the forward history.

On macOS, install the architecture-matched DMG and copy `OpenProgram.app` to `/Applications`; current macOS releases are Developer ID signed and Apple notarized. On Windows, install only the signed `win-x64.exe` or `win-arm64.exe` attached to a published [GitHub Release](https://github.com/FuzzyKuji/OpenProgram/releases). If a release has no signed Windows EXE, use the CLI/server and browser UI for that version. The complete steps are in [Installation](../install/install.md).

Terminal panes use the login shell on macOS and Windows PowerShell through ConPTY on Windows. Right-click any terminal view (a Terminal or Claude Code tab, an agent terminal or background terminal in Resources, or the terminal preview) for **Copy**, **Paste** (in views that take input) and **Add selection to chat**, which adds the selected output to the focused conversation's draft as a code block. Packaged apps on both platforms start the worker from their embedded managed Python and do not depend on a system Python or Node.js. When the worker is not reachable at startup, the App starts it and shows **Waiting for backend to start...** until it answers, checking every second. While an installer is replacing the App and its runtime (an update, or a local refresh) the page shows **Updating OpenProgram...** instead; the App starts no worker then and reconnects on its own once the installer is done.

When running Desktop from source on Linux, terminal panes use an installed absolute `SHELL` path, then fall back to `/bin/bash` or `/bin/sh`. They do not require zsh. If no shell is available, the terminal reports the missing prerequisite before starting a process.

Opening a conversation from a session tab reuses that tab, even when another tab displays the same conversation. A launcher also opens its own independent instance. From other page kinds, an existing session tab can be selected or a new one opened. Back and Forward always stay in the selected tab. Draft input and background title updates survive navigation and reload; deleted sessions are removed from every history.

## Opening the Browser

Create a pane and select **Browser**, or open a new browser tab from the app tab bar. The Browser home shows the same browser chrome used by loaded webpages:

- Back, Forward, Reload/Stop, Home, the address/search field with its bookmark-current-page star at the right end, Bookmarks, open externally, and the Browser menu. While you are not editing it, the address field shows the site's host in full contrast and the rest of the address dimmed; a lock marks HTTPS pages.
- A bookmarks bar that is visible by default and can be hidden from the Browser menu or Browser settings.
- Responsive controls: less frequent actions move into the Browser menu when the pane is narrow; the address field, Back, Reload/Stop, bookmark-current-page, and menu remain available.

The Browser menu owns browser-specific actions: new browser tab, Bookmarks, History, bookmarks-bar visibility, profile import, clear browsing data, and Browser settings. Window and pane actions remain in the OpenProgram window menu.

Web tabs display the site favicon in both ordinary and split tabs. While an icon loads, or if it is unavailable, invalid, or fully transparent, the desktop App shows the standard browser icon instead. Reopening a retained page restores its current icon without reloading the page.

If a webpage asks to confirm leaving during Reload, Back, Forward, or navigation, the App displays a confirmation. **Stay on page** is the default and cancellation action. Choose **Leave page** to continue the pending operation; unsaved changes may be lost.

While a page loads, Reload becomes **Stop loading** (an X icon), and an animated line appears below the browser toolbar. Click Stop loading to cancel. The line disappears when loading finishes or stops; reduced-motion settings keep it static.

Keyboard shortcuts apply to the Browser tab in the focused pane (Ctrl replaces ⌘ on Windows): ⌘R reloads the page and ⇧⌘R reloads it bypassing the cache; ⌘L selects the address field; ⌘[ and ⌘] go back and forward; ⌘F finds in the page; ⌘+, ⌘− and ⌘0 zoom the page; ⌘P prints it. When the focused pane is not a Browser tab, ⌘R reloads the App window, which also reloads its open webpages. ⌘K opens the App's [command palette](web.md#command-palette) even while a webpage has focus.

To point the agent at part of a page, open the page's **⋮** menu and choose **Comment on the page…**, then click an element. The page outlines the element under the pointer; Esc or the X on the comment row cancels. Type a comment and choose **Add to message**: the composer of a conversation gets a block naming the page title and address, the element's CSS selector and visible text, and your comment. The comment goes to the conversation in focus, else the one whose agent opened the page, else the one you were last in; the confirmation names it. Nothing is sent until you send the message, so you can comment on several elements first. Picking runs in a separate script context the webpage cannot see.

To show the agent part of a page as an image, choose **Screenshot a region…** in the same menu and drag over the area. The size shows while you drag; a click without a drag starts over, and Esc or the X on the hint row cancels. The capture is added to the composer as a PNG attachment named after the site and its size, in the same conversation a comment would go to. The selection is drawn in the same separate script context and removed before the capture, so it never appears in the image.


## Page navigation, popups, and right-click actions

The webpage decides whether an action navigates its current page or requests a new browsing context. Ordinary links, form submissions, and same-page navigation stay in the current Browser tab. Links with `target="_blank"` and scripts that call `window.open()` create a distinct Browser tab and activate it immediately.

Right-click a link inside a webpage to open it in a new Browser tab or copy its address. A page context also provides Back, Forward, and Reload; editable fields provide Undo, Redo, Cut, Copy, Paste, and Select All when the webpage reports that each action is available. These actions apply only to the exact Browser tab that opened the menu.

## Bookmarks and History

The bookmarks bar shows the direct contents of the imported or locally maintained Bookmarks bar. Items that do not fit appear in the double-chevron overflow menu. The separated **All bookmarks** button on the right opens the Bookmarks manager, including the original Other bookmarks and Mobile bookmarks folders. Folder names, order, and contents remain unchanged. Nested menus open one level at a time and remain scrollable within the current window.

Website bookmarks display their saved favicon, falling back to the website’s own `/favicon.ico` and then a browser icon if unavailable. This applies to the bar, folder menus, and manager. Adding a bookmark preserves the current page icon; reopening a bookmarked URL updates it when the page provides a new icon. Icon requests do not send a referrer or use a third-party favicon service. Shortcuts on the Browser home page show the website's own `/favicon.ico`, or the site's initial when it has none.

To add a homepage shortcut, select **Add**, enter an address and an optional name, then select **Add** or press Enter. The compact editor follows your interface theme and font. Cancel, Close, Escape, clicking outside, or selecting the Add tile again dismisses it and clears the unfinished entry.

During use, decoded icons are shared across the bar, folder menus, and tab components in each renderer. Reopening a bookmark menu reuses its document and icon cache; icons do not restart from the loading placeholder on every opening. The cache is bounded, retries failed sources after five minutes, and refreshes reused sources after thirty minutes when requested again. Closing the window releases its retained bookmark menu. Restarting the App can load icons again through the browser cache.

The Bookmarks manager has a folder tree, current-folder list, search, favicon display, and item menus. History is grouped by local date and uses compact rows with time, favicon, title, and domain. Desktop Browser data is separate from backend state: History and the persistent `webtabs` partition live in Electron's per-user application-data directory, while chats, projects, Programs, and worker configuration remain under `~/.openprogram/`. Clearing browser data does not delete that backend state.

## Importing an existing browser profile

On macOS and Windows, OpenProgram can discover local Google Chrome, Brave, Microsoft Edge, and Chromium profiles. Import is always explicit: choose the source browser, profile, and any of the supported data types.

| Data | Behavior |
|---|---|
| History | Copies up to the supported limit of HTTP/HTTPS visits and merges them into OpenProgram History |
| Bookmarks | Preserves the bookmarks-bar, other-bookmarks, mobile-bookmarks, and nested-folder structure while filtering invalid URLs and duplicates |
| Cookies | Uses a temporary source-browser process to decrypt eligible cookies, validates them, and writes them through Electron's cookie API; some sites still require a new login |

OpenProgram does not import passwords, payment or address autofill data, downloads, cache, localStorage, Service Workers, browser extensions, or extension storage. It does not modify the source profile.

## Agent access to a split Browser pane

When a chat turn has a visible built-in Browser pane in the same app window, OpenProgram attaches a bounded description of that exact WebTab to the turn before the first model response. The Agent receives the page title, origin, visible text, ARIA landmarks, and a browser-control tool. This works whether the Browser pane is on the left or right, in a picture-in-picture preview over chat, and does not require the app window or Browser pane to have operating-system focus.

If the Agent opens a page while you stay in chat, Desktop shows that live WebTab as a small corner preview. In a split window the preview stays over its chat while you work in another pane. Click **Close preview (X)** in its header to hide the small window; the page remains available to reopen from **Session resources** in the right sidebar. **Open page** displays the full page. The web UI (a browser tab, not the Desktop App) has no native BrowserView, so the same preview falls back to an iframe or an Open-in-new-tab control.

Actions remain bound to the originating window and WebTab. The default path uses DOM, ARIA, page text, and element references. A single current-viewport screenshot is used only for a visual task or when the page cannot be located structurally. The product does not add OCR, object detection, iterative crops, component memory, vision memory, or workflow replay to this path.

Each preview belongs to its conversation, even when you navigate between conversations within the same chat tab. Switching conversations hides the previous preview and restores the selected conversation’s preview. Pages retained only in a conversation are invisible and inaccessible to other Agents. **Open page** exposes that same Page as a regular tab, where another conversation can discover it and acquire control after the current Agent releases its exclusive control. Opening a tab does not transfer the original conversation’s preview.

The preview header shows Auto preview or Fixed preview. Auto preview tracks the page the Agent is operating. In **More**, check **Automatically show the page the Agent is using** to enable automatic selection; uncheck it to keep the current page. The application menu shows a checkbox with a separate explanation underneath, in both desktop and Web. Checking or unchecking an option updates it immediately and keeps the menu open. Press Escape or click outside to dismiss it. The page indicator beside the composer shows the page title without a Left/Right/Center position label. This does not mean always-on-top. The header has no pin or expand/shrink button. This selection does not change the Agent’s target, resume or start the Agent, or change the page’s lifetime or top-tab placement. Session resources has no separate pin control. The default chat preview is 300×198.75 (300×168.75 image plus the header). Drag the header to move it; resize from any of the four edges or four corners. The overlay keeps the image aspect ratio (16:9 by default). There is no visible corner grip; the pointer changes at the outer border. Resizing the preview does not resize or zoom the underlying page. In Resources, each group heading is a full-row control with a trailing chevron.

## Browser extensions

Chrome Web Store and Edge Add-ons pages open as ordinary webpages, but OpenProgram does not install browser extensions, download CRX packages, import extensions from another browser, or provide an extension manager. The app uses standard Electron/Chromium. Electron exposes only part of the Chrome Extensions API and explicitly does not target compatibility with arbitrary Chrome Web Store extensions; OpenProgram does not maintain a custom Chromium/Electron fork or add another browser runtime for extension compatibility. The Playwright Chromium shipped with the complete runtime belongs to the browser automation backend; it does not host the Desktop Browser Pane or extensions.

Use [OpenProgram Plugins](../capabilities/plugins.md), Skills, MCP servers, Programs, or agent tools to extend OpenProgram itself. These do not modify the embedded webpage runtime.

The maintained engineering specifications are [Built-in browser design](../reference/design/ui/browser/built-in-browser.html) and the [Web Use / Computer Use boundary](../reference/design/integrations/web-use.html).

## Session resources

In a split canvas, clicking a chat selects the conversation for Files, Activity and Resources. Clicking a webpage keeps the last selected visible chat in that canvas. Drag a webpage tab or its pane handle onto Resources to attach it to that conversation. A split tab containing one webpage attaches that webpage only; with multiple webpages, drag the desired page's pane handle. During the drag, a blue preview marks the destination and shows **Release to add to Resources** while you hover. Releasing opens Resources after the attachment succeeds and displays a confirmation. If it fails, a retry message appears and the webpage stays available.

Click **Resources** in the right sidebar to open **Session resources**. Use the sidebar toggle to collapse or expand the panel. The panel shows only resources owned by the selected session. There is no search field. Switching sessions updates the listed resources. Groups use resource types in a stable order: Webpage, VM, Desktop, Terminal, Application, Container, Remote environment, and Other resources. Empty types are omitted; session and page names do not determine groups. Collapse state is saved per session and type; collapsing only hides rows. Existing Preview in conversation, Open in tab, and Close webpage buttons stay unchanged. Selecting a non-web resource hides the webpage preview and uses that resource’s existing view or details. The panel lists complete software/environment objects: webpages, VM or desktop attachments, and actual container or remote-environment objects registered by integrations. Code executions, commands, scripts, background processes and output belong in Activity. File views remain separate. Persistent Terminal environments appear in this same resource list after they are associated with the session. Views without recorded session ownership and new draft chats show no session resources. Opening an owned resource keeps its session context.

Agent-created webpages with recorded session ownership stay out of the top strip unless pinned or in a split. Legacy pages without an owner remain in the top strip. Select a webpage to open its existing view. Webpages can be pinned or closed; collapsing the panel or a group leaves resources running. Selecting a resource keeps the panel open beside its view. Closing a webpage removes its active row immediately while the close request is processed. If closure is not confirmed, the row becomes available again.

Docker and SSH commands stay in the execution/Activity flow; running a command does not create a software resource. The one exception is a command the Agent left running in the background, which is listed as a Background terminal (see Shared Terminal environments). While a `computer_use_agent` call runs, it lists the application or VM it controls (a Desktop row named after the app, or the configured VM). Other integrations must register the actual software/environment object and its identity, rather than a command, image name or process. Select an environment resource to inspect its target and status.

Integrations can report complete software/environment objects through `openprogram.host.resources.session.resource_use(kind, title, target)` inside a trusted runtime session. The context records the actual session automatically and releases the usage on exit. OpenProgram does not infer resources from arbitrary shell command text. URL resource identities omit credentials, query parameters, and fragments.

## Running conversations after restart

Recoverable running conversations continue automatically in the same conversation when the worker restarts, using the input and execution results recorded during normal operation. New restart intents have no default time limit. No separate save action is needed, and no message is added to the conversation: the instruction to continue goes to the model only, and the interrupted reply and its continuation show as one reply. Expanding its steps shows a **Worker restarted, continued** step where the restart fell. Manually paused, cancelled, and completed tasks remain stopped. A task interrupted after you already sent a newer message in that conversation also stays paused; continue it from Activity if you still want it. Confirmed tool results are reused; an operation whose external result is still unknown requires reconciliation before it can continue. Reconnecting the interface keeps the existing transcript.


Conversations show normal messages and tool results, including results of an update you requested. They do not contain a separate software-update history, update controls, or update recovery notices. Opening a conversation does not start software-update history polling.

## Windows reopen after quitting

Windows you tore off the main window come back when the App starts again, at their last place on screen and with their tabs. A window you closed before quitting stays closed. A window whose last place is off every display opens at its default place.

## Notifications and keep-awake

When OpenProgram is in the background, the desktop App sends a system notification when a session's turn finishes, stops with an error, asks you a question or for approval, or waits for system access. No notification appears while any OpenProgram window is in front. Each event notifies once, even with several windows open. Stopping a turn yourself does not notify. Click a notification to bring its window forward and open that session.

While any session is running, the App keeps the computer from idle-sleeping. The display can still turn off. The hold ends when no session is running.

**Notification sound** picks the sound: the system default, none, or on macOS one of the system sounds, which plays once when chosen.

Turn either behavior off in **Settings → General → Notifications**. The choices apply to this computer and persist across restarts. The browser interface at http://localhost:18100 sends no notifications and does not keep the computer awake.

## Restart and retained browser pages

After the Desktop App or worker process restarts, pages you had not closed come back automatically in the background. The App keeps the same retained tab, session, and branch ownership, and the last confirmed address and title. It creates a new live page behind that retained tab; handles from the previous process are no longer valid. It does not open a second copy of the same retained tab, does not reopen a page you closed, and does not show a preview you had hidden. Compact picture-in-picture chrome, the vertical Files / Activity / Resources sidebar, and grouped resource rows stay as they were. Labels follow the App language setting.

While a page is coming back, its row stays in its resource type group and shows **Restoring page…**. If restore fails, the same row shows **Could not restore page**. If the new live page later needs a new connection, the row shows **Reconnect**. Those rows do not move into a generic Unavailable group. Explicitly closed pages and exited terminals leave the active resource list. Restoring a page does not start or continue an Agent. Idle pages stay ready to use. A new task still observes the page and checks permission as usual. Restore reloads the last confirmed URL with site storage already in the Desktop `webtabs` partition; unsaved DOM and form fields from the previous process are not restored. An older resource record with no retained tab descriptor is not recreated automatically; that row stays in its original group as **Could not restore page**. This bounded restart behavior is implemented in the default App.

An Agent that was using a page when the App or worker restarted continues with the browser tool instead of failing in a loop:

- Listing pages waits up to 20 seconds for the App to reconnect. If the App is still not connected, the tool reports `desktop_unavailable` and asks the Agent to list pages again after a few seconds. If the originating window is gone, pages in the other open windows are listed.
- A session or page token from an earlier turn of the same conversation leads back to the same tab: the tool observes that tab again and returns the fresh observation. The previous action is never repeated, and a page you closed is not reopened.
- If that tab is no longer known, for example after the worker restarted, the error lists the current pages with fresh tokens. The Agent observes the task page with its token in one call.
- A screenshot right after navigation or another action takes a fresh observation first, so it does not fail as stale.


## Browser interaction and pause

You may click, scroll, type, navigate, or close built-in pages while an Agent works. These actions do not pause the Agent. Agents may also operate OpenProgram's own web interface. Use the task pause control next to the conversation composer to pause execution.

When a task page disappears, the Agent reacquires the page or reopens its last known address if it has closed, then reads its current state. Previous clicks and submissions are not replayed automatically. Lost authentication or unsaved content is reported when it cannot be restored.

Conversation history loads the latest page first. Scrolling retrieves nearby messages automatically in either direction while keeping your reading position and new streamed output. No loading button is needed; failed requests retry automatically. Distant pages leave the memory cache and are retrieved again when you return. Reopening a conversation restores the visible message when it still exists on the selected branch. Jump to latest retrieves the latest page directly. The DAG is loaded when you open its view; ordinary Chat does not calculate its drawing coordinates. Rendered Markdown uses a bounded cache, so previously viewed long content does not accumulate without limit. Stored history and model context are unchanged.

The main conversation and split panes each provide Jump to latest while newer messages remain outside the loaded window. A failed jump keeps the control available for retry. Scrolling, clicking inside the transcript, or pressing a key there cancels a pending jump or saved-position restoration; late replies do not replace the window you are reading. Closing a pane saves its final reading position. Reconnecting resumes automatic history loading without waiting for an old retry delay.

## Continuing after a restart

Closing a conversation tab or the App window leaves worker-owned tasks running. If the worker itself stops, resumable Agent tasks save checkpoints at completed provider and tool boundaries. On restart, tasks paused by shutdown or recovered from a safe abandoned checkpoint automatically continue without a default time limit. An explicitly configured deadline is persisted; another restart does not extend it. After such a deadline expires, the task stays paused and can be continued manually. Previously persisted finite deadlines are preserved when upgrading.

The setting `execution.auto_resume_window_seconds` defaults to `-1` (no time limit); `0` disables automatic restart continuation, and a positive value sets an explicit interval in seconds. Explicit Stop/Cancel, manual pauses, and unanswered approvals do not automatically continue. An operation whose external result is unknown requires reconciliation. Continuation preserves the original task identity, permissions, and resource admission, and requires a compatible runtime contract. This restores durable checkpoints, not arbitrary process memory or unsaved external application state.

Self-update continuation, replanning after a changed runtime contract, and original-conversation follow-up use this setting too, measured from the completed update’s last recorded activity. A continuously running update is not stopped by this continuation timer.

### Shared Terminal environments

Select a Terminal resource to attach its interactive view beside the conversation. The Agent and the user share the same shell, working directory, environment and output. Hiding the view or switching sessions does not terminate the shell. **Terminate terminal** explicitly requests process termination and requires confirmation; an acknowledged request is not evidence that the process has exited. **Share terminal** makes it discoverable to other sessions on that Desktop host; making it private revokes the current Agent binding.

Typing into, interrupting or closing a terminal tab follows the permission mode, whether you opened the tab or the Agent did. When approval is asked, the card names the tab, its current directory and whether a command is running in it, and shows exactly what would be typed.

Commands the Agent left running with `bash` are listed in the same Terminal group as **Background terminal**. Selecting one shows its output read-only, with **Stop**; the Agent types into it with `write_stdin`, not through this view.

Terminal input delivery does not indicate command success. After an uncertain input result, OpenProgram does not resend it. **Reconnect view** reads the current output again without replaying input. An unfinished human input fragment or changed input revision prevents conflicting Agent input until the Agent observes the terminal again.

For ordinary macOS zsh and compatible Bash 3.2 login shells, `terminal_use(action="observe", ...)` and `resource(provider="terminal", action="observe", ...)` also return optional `shell_integration` metadata reported by the shell:

| Field | Meaning |
|---|---|
| `status` | `starting`, `ready`, `unavailable`, or `ended`. |
| `mode`, `reason` | The selected integration (`zsh-hooks` or `bash-debug`) and an unavailable reason, when present. |
| `event_sequence` | Sequence of the latest accepted shell report. |
| `cwd` | Latest reported directory in `value`, with its `event_sequence`; `null` before a report. |
| `cycle` | Foreground command cycle `id`, `phase` (`running`, `finished`, or `unknown`), and `exit_code`; `null` before the first command. |

`start_cwd` remains the starting directory, and the top-level `exit_code` belongs to the terminal process. A cycle's exit code is reported only after its matching foreground completion; background jobs can still be running. Input receipts retain `command_complete=null`: input delivery, shell completion, and successful external effects are separate facts. Reports do not grant permissions and can become stale if shell hooks are changed.

Existing bash-preexec, custom DEBUG traps, existing or replaced prompt commands, readonly prompt configuration, and incompatible tracing settings fall back to `unavailable` without replacing the user's hooks. Unsupported shells and presets retain normal terminal input/output. Missing metadata from older hosts or `unavailable` metadata means the command state is unknown; do not infer success from a prompt or quiet output. These fields are tool observations, not additional terminal controls.

### Common Agent resource interface

The `resource` tool provides `describe` plus provider-declared operations. Start with `resource(action="describe")`, then use the returned provider name and argument schema. The built-in `web` and `terminal` providers preserve their native identities and checks. For example, `resource(provider="terminal", action="list")` discovers available shells; `observe` returns the exact generation, binding, input revision and output cursor required for subsequent operations. Existing `web_use` and `terminal_use` remain available. For a web Page, `release` ends the Agent's control session and leaves the Page open; `close`, in `resource` and in `web_use`, closes the Page's tab and reports `page_closed`. A close that the App does not confirm returns an error instead.

Providers only expose supported operations. Web `release` releases a control session and leaves the Page open; `close` closes the exact observed Page using its owned control binding. Terminal `release` releases Agent control and leaves its process running; `close` requests termination. Local Terminal operations require a live execution in the originating Desktop window and cannot bypass a task sandbox.

Trusted Python integrations can register a `ResourceProvider` with `openprogram.host.resources.registry.register(...)`, declaring a JSON Schema for every supported operation and a callable adapter. The adapter is responsible for its native authorization and resource lifecycle. Registration rejects duplicate provider names and validates arguments before invoking the adapter. This is a trusted integration API, not a loader for arbitrary code supplied by the Agent or a webpage. Integrations can use the existing `openprogram.host.resources.session.resource_use(...)` context to report session usage in Resources. Enabled installed applications automatically register `application.<id>` from their operation manifest. Their session-associated instances open in Resources using the existing isolated application view.

Browser tasks reuse an explicitly selected Page without reloading it or opening a replacement. Each action returns to the browser workflow for a new observation and verification. Reaching an execution safety limit stops the task instead of retrying completed actions; cleanup retains the calling conversation identity.

## Programs loading

Abilities → Programs has two roots. **Tools** holds the built-in tools of `openprogram/programs/tools/`, grouped by category. **Applications** holds every application: the built-in ones from `openprogram/programs/applications/`, marked built in, and the installed ones in `~/.openprogram/programs/` (your packages, catalogued applications and installed harnesses), marked installed. Each application expands to its entries and source files. Its detail shows whether it is disabled and, for one of your packages, whether it failed to load or is not callable yet. A catalogued application inside another application's directory is listed on its own and names the directory it lives in. The page opens on the first application, or on the first tool when there is none.

Abilities → Programs keeps its directory tree, selected Program and loaded call graph when you leave and return. Expanded folders and the selected graph are checked in the background every five seconds while the page is visible, and when focus returns. Unchanged files reuse their analysis. Refresh checks for changes without resetting your selection or expanded folders. A failed check retains the last loaded content so you can retry.

Browser tasks can select a user-approved local file with `upload`, a fresh file-input `ref`, and `path` (up to 50 MiB). Upload uses the normal permission gate even for an already selected Page, because selecting a file can immediately transmit its contents. File read restrictions still apply. Observations expose selected filenames, not file contents or local paths. `file_selected` verifies selection only; confirming upload acceptance requires a separate assertion against the website response. An uncertain upload is not automatically repeated.

Verification uses `assertion` and a non-empty `value`; `text` is for typing or reporting a blocker. Three consecutive failed actions or unmet assertions on the same observation stop with the actual failure reason. Permission or execution rejection stops without repeating the action. A reported blocker never counts as completion, and action counts measure Page mutations rather than model calls.
