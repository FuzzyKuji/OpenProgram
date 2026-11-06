# Agent avatars

Every Agent has a picture, and the picture stands beside the Agent's name
wherever the interface names it. An Agent that was never given one shows a
character derived from its id, so no surface falls back to a generic icon
and no stored Agent needs a migration.

Agents use the same `Avatar` component and the same `AvatarConfig` as the
user's profile picture (`apps/web/components/avatar/`). The character is one
more `kind` of that config, next to `dicebear`, `upload` and `letter`; there
is no second avatar system.

## The character

A character is a flat coloured shape with two eyes: a speech bubble, a mug, a
rocket, a ghost. Alive, it blinks, sways, and looks around on its own; its
motion is how it shows what it is doing. It does not follow the pointer.

| Part | Values |
|---|---|
| Shape | 22: `chat`, `controller`, `mug`, `lightbulb`, `sprout`, `watering-can`, `barbell`, `book`, `brain`, `bull`, `bunny`, `camera`, `cat`, `cloud`, `ghost`, `magnifier`, `paint-brush`, `palette`, `rocket`, `shield`, `star`, `witch-hat` |
| Colour | 8 named colours: `blue`, `orange`, `green`, `violet`, `pink`, `teal`, `yellow`, `red` |
| Eyes | white |
| Mood | `idle`, `thinking`, `happy` |

The catalogue lives in `components/avatar/bot/catalog.ts`. A colour is stored
by name and drawn in one fixed hex value. Character art is the one place that
does not take its colours from the theme: the colour is part of who the
character is, the same way a generated DiceBear picture keeps its colours in
every theme. Everything around the character (tiles, rings, labels) still uses
theme tokens.

## The character an id gets

`botLookFor(id)` in `components/avatar/bot/identity.ts` gives every id a shape
and a colour. A 32-bit FNV-1a hash of the id picks the shape from its low bits
and the colour from its high bits, so the two do not move together. The
built-in Agents are a table instead: each wears a character that fits its job
(the PR Verifier a shield, the Research Desk a brain, the Knowledge Keeper a
sprout), and no two share a shape.

`agentAvatarConfig(agent)` in `lib/agents/agent-avatar.ts` is the single rule
for what an Agent shows: its saved avatar, or the character of its id when it
has none (or when it has an upload whose picture is missing).

## Storage

The avatar is a field of the Agent record (`AgentSpec.avatar`,
`<state>/agents/<id>/agent.json`) and travels in every Agent listing.

| Field | Used by | Rule |
|---|---|---|
| `kind` | all | `bot`, `dicebear`, `upload` or `letter`; required when the avatar is not empty |
| `shape`, `color` | `bot` | a short slug; the web catalogue decides which exist, and an unknown one draws the id's character |
| `style`, `seed` | `dicebear` | a slug; up to 120 characters |
| `file` | `upload` | a `data:image/` URL of at most 350,000 characters |
| `letter`, `bg` | `letter` | up to 2 and 40 characters |

- `{}` means "no avatar of its own" and is the default.
- A patch replaces the avatar whole. Switching from an upload to a character
  leaves nothing of the picture behind.
- The API validates strictly and refuses anything else with 400
  (`validate_avatar` in `openprogram/runtime/agent_registry/manager.py`).
  Loading is tolerant: a stored avatar that no longer validates reads as `{}`,
  so a bad picture never hides an Agent.
- Uploads are capped at 256 KB in the picker because the picture is carried
  by every listing.
- A trial conversation's configuration snapshot leaves the avatar out; it is
  how the Agent looks, not how it runs.

## Rendering

The renderer is the `open-bot-avatar` package. `components/avatar/bot/runtime.ts`
loads it on first use, the way the optional DiceBear styles load, so a page
without a character never pays for it. `BotAvatar` mounts into a host element
of the asked size and updates or destroys the mount with the component.

| Mode | What is drawn | When |
|---|---|---|
| Still | one static SVG | `Avatar`'s default |
| Live | a canvas that blinks, sways and looks around | `live`; `AgentAvatar`'s default |

The renderer prepares a shape the first time it draws it: it infers the
shape's volume from its outline, 25 to 90 ms a shape, and keeps it for the
page's life. Seventeen Agents shown for the first time, as the Agent menu
does, asked for over half a second of that in one frame. So
`components/avatar/bot/warm.ts` prepares shapes one per task: a shape a
character on the page is waiting for in the next task, the rest of the
catalogue in idle time once the renderer has loaded, so a list usually opens
with every shape ready. Until its shape is ready, and in server markup, a
character is its flat glyph (body and white eyes in its own colours) in the
box the renderer will draw into; the renderer mounts in its place in the
same commit, so nothing flashes. A still picture needs the same preparation,
so making characters still would not have helped.

Live characters share one animation loop for the whole page and pause while
they are off screen. When the system asks for reduced motion, a live character
is the still picture.

A live, idle character looks around on its own. The renderer's built-in
idle wander moves the eyes about a pixel at icon size, and every character
of one shape moves in step with it, so it reads as staring ahead.
`components/avatar/bot/wander.ts` gives each character its own glances
instead: a look target (`lookAt`) that the renderer turns the eyes and the
body toward, held for 0.9 to 2.6 s, then the next one. A glance goes at
least a third of the way to one side (x up to 0.95, y up to 0.6 of the
range), and one in four comes back to straight ahead. Every character draws
its own targets and pauses and starts after a random pause, so characters
side by side look different ways. It is one timer per character, firing once
per glance; nothing runs per frame. A thinking or happy character keeps its
mood's pose instead. It does not look toward the pointer. A
character tracking the cursor reads as watching the user, which is not what
an Agent's picture is for, and the renderer's pointer following
(`followPointer`) would measure the character with `getBoundingClientRect`
in every frame, forcing style early in whatever else that frame does.
`followPointer` stays off, so the animation loop never reads layout. The browser stops the loop's frames while the page is hidden.

The character's silhouette is the picture, so it is not clipped to a circle
and has no tile behind it. Uploaded and generated Agent pictures keep a
rounded-square frame.

A character is an illustration, not an icon. Toggles, menu rows and buttons
size the svgs inside them as icons; one rule in `app/styles/design/icons.css`
keeps a character's drawing at the size of its body box.

### Optical size

The drawings leave different margins inside their 100-unit box: Main's cloud
is wide and short (82 x 52 units), the ghost narrow and tall (54 x 76). Drawn
at the box's size, a 16 px character showed a body of 13 x 8 px beside icons
whose ink is about 14 x 13.5 px, so it looked smaller than its neighbours.
`BotAvatar` therefore has two boxes: the slot, at the asked size, which takes
part in layout; and the body box inside it, which the renderer draws into.
`botFit` in `components/avatar/bot/catalog.ts` scales and places the body box
from the body's extent (`BOT_EXTENTS`, checked against the drawings by a
test): the body's geometric mean side becomes 0.8 of the slot, no side longer
than 0.94 of it, and the body is centred. A 16 px cloud is about 15 x 9.5 px,
a ghost about 10.7 x 15 px. A live canvas is sized to the body box, so it is
drawn at the size that shows rather than scaled up.

### Hover

The slot pops on its control's hover exactly as an icon does
([icons](icons.md), motion contract): `components/ui/hover-pop.ts` holds the
clickable-host selector, the 1.12 scale and the spring, and `SolarIcon` and
`BotAvatar` both use it. The composer's Agent chip, the rows of the Agent
menu and every other control that shows a character move it the same way as
the icons beside it; outside a control the character follows its own hover.
Reduced motion turns it off.

## Where it shows

| Surface | Size | Mode |
|---|---|---|
| Agents page: card, quick settings head | 32 | live |
| Agents page: editor header | 40 | live |
| Agents page: list rail | 16 | live |
| Avatar picker shape tiles | 34 | still |
| Composer Agent chip | 16 | live |
| Agent menu rows | 16 | live |
| Name above a reply from an Agent other than the default | 18 | live |
| Activity panel: Always-on row | 22 | live, `thinking` while the Agent works |
| Activity panel: Always-on detail head | 16 | live |
| Settings: channel bindings | 16 | live |
| Graph: agent reply and sub-agent start nodes, legend | 16 | flat glyph in the branch colour |
| Activity panel: agent and sub-agent rows | 22 (16 in a detail head) | flat glyph in the branch colour |

A character that stands for an Agent is alive on every surface, however
small; `AgentAvatar` is live unless a caller turns it off. The picker's shape
tiles are samples of a shape, not an Agent, and stay still.

Surfaces that hold only an Agent id use `AgentAvatarById`, which reads the
shared Agent list (`useAgents`) and shows the id's character until the list
has loaded. The Agents page writes its own list into the same cache, so a
saved avatar shows everywhere without a reload.

Where a character stands in for an icon inside a coloured chip or row (the
graph, the Activity panel), it is a flat glyph (`components/avatar/bot/glyph.ts`,
`BotGlyph` in React): the body's path in the current colour and the eyes cut
through it. The outlines wind clockwise and the body's winding number under
each eye is 1, so each eye is a pill drawn counter-clockwise and the nonzero
fill rule cuts it out; a test checks this for every shape. Its view box fits
the body like an icon, by the same `botFit` as a live character. The glyph
does not move: it is cloned into the graph's SVG like a Solar icon, and its
colour is the branch's (see the graph's [rendering record](../../runtime/dag/rendering.md)).
The main agent's glyph is the conversation Agent's character
(`useConversationAgentShape`; an Agent pictured by an upload or a generated
image uses its id's character there); a sub-agent's is the one its name gives.

The page icons for Agents (the navigation entry, the center tab) and the
`ghost` of the transcript's sub-agent tool calls are icons of a kind of thing,
not pictures of one Agent; they stay icons.

## The picker

The Agent editor's General section uses the same `AvatarPicker` as the profile
settings, with its sources set to Character, Generated and Upload. Character
shows the shape tiles and the colour swatches; the tiles preview the current
colour. The picker edits the Agent's draft, so the avatar saves and discards
with the rest of the configuration.

## Sources and licences

| Source | What it provides | Licence |
|---|---|---|
| `open-bot-avatar` (npm, pinned) | the renderer and 7 shapes | MIT, Copyright Dominik Scholz |
| The same project's repository gallery | 15 more shapes, copied unchanged into `components/avatar/bot/gallery.ts` with the licence notice | MIT, Copyright Dominik Scholz |

The shapes are the project's own designs. Alternatives that were weighed and
are not used:

| Alternative | Why not |
|---|---|
| Renderers extracted from the Grok Bot client, and replicas of its characters | The code or the character designs belong to xAI, whatever licence the repository states |
| `@aora-bot/react` | Its licence is not open source (attribution and team-size terms), and it needs React 19 |
| `agent-robot-avatar` | One robot design whose character identity is reserved by its author |
| DiceBear Bottts, Facehash, animated emoji sets | A different look from the one chosen: generated robots, letter faces, or emoji that do not read as one family |

## Implementation status

Everything above is implemented. The `happy` mood is available to callers and
no surface sets it yet.
