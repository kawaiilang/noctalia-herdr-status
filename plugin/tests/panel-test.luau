local function findNodes(node, kind, out)
    out = out or {}
    if type(node) ~= "table" then
        return out
    end
    if node.kind == kind then
        table.insert(out, node)
    end
    for _, child in ipairs(node.children or {}) do
        findNodes(child, kind, out)
    end
    return out
end

local function findButtons(node)
    return findNodes(node, "button")
end

-- Offline state renders stopped message without an Open Herdr button
noctalia.state.set("status", {
    state = "offline",
    running = false,
    counts = { blocked = 0, working = 0, done = 0, idle = 0, unknown = 0, agents = 0, shells = 0, total = 0 },
    agents = {},
    shells = {},
})
onOpen({})
assert(values.refresh == 1, "onOpen must request refresh")
assert(displayed.tree ~= nil)
for _, btn in ipairs(findButtons(displayed.tree)) do
    assert(btn.props.glyph == "refresh" or btn.props.glyph == "close", "offline panel must not expose launch CTA")
end

-- Online state groups agents by workspace with highest-urgency workspace first
noctalia.state.set("status", {
    state = "blocked",
    running = true,
    counts = { blocked = 1, working = 0, done = 0, idle = 1, unknown = 1, agents = 3, shells = 1, total = 4 },
    agents = {
        {
            pane_id = "p7",
            name = "reviewer",
            agent = "codex",
            status = "blocked",
            dir = "nixos",
            workspace = "infra",
            tab = "review",
            focused = false,
        },
        {
            pane_id = "p6",
            name = "agy",
            agent = "agy",
            status = "idle",
            dir = "math",
            workspace = "math",
            tab = "agy",
            focused = false,
        },
        {
            pane_id = "p8",
            name = "builder",
            agent = "pi",
            status = "unknown",
            dir = "nixos",
            workspace = "infra",
            tab = "build",
            focused = true,
        },
    },
    shells = {
        {
            pane_id = "p9",
            name = "shell",
            agent = "",
            status = "shell",
            dir = "nixos",
            workspace = "",
            tab = "shell",
            focused = false,
        },
    },
})

local buttons = findButtons(displayed.tree)
assert(
    displayed.tree.children[2].children[1].props.text
        == "count_blocked:1 · count_idle:1 · count_unknown:1 · count_shells:1"
)

local scroll = displayed.tree.children[3]
assert(scroll.kind == "scroll")
-- Agents section label, then workspace cards ordered by urgency: infra (blocked) before math (idle)
assert(scroll.children[2].children[1].children[2].props.text == "infra")
assert(scroll.children[2].children[1].children[2].props.color == "error")
assert(scroll.children[3].children[1].children[2].props.text == "math")
assert(scroll.children[3].children[1].children[2].props.color == "secondary")
-- Shell with empty workspace uses fallback label
local shellCard = scroll.children[#scroll.children]
assert(shellCard.children[1].children[2].props.text == "panel_workspace_unassigned")

-- No label uses unsupported wrap prop
for _, lbl in ipairs(findNodes(displayed.tree, "label")) do
    assert(lbl.props.wrap == nil, "label must not emit unsupported wrap prop")
end

local foundUnknown = false
local focusBtn = nil
local focusedSelected = false
local deduplicatedMathText = false
for _, btn in ipairs(buttons) do
    if btn.props and btn.props.key == "entry-p7" then
        focusBtn = btn
    elseif btn.props.key == "entry-p8" then
        foundUnknown = string.find(btn.props.text, "item_unknown", 1, true) ~= nil
        focusedSelected = btn.props.selected == true
    elseif btn.props.key == "entry-p6" then
        deduplicatedMathText = btn.props.text == "agy (item_idle) · p6"
    end
end
assert(foundUnknown)
assert(focusedSelected, "focused pane button must set selected = true")
assert(deduplicatedMathText, "tab/dir matching title/workspace must not repeat in button text")
assert(focusBtn ~= nil, "panel must render clickable button for blocked agent p7")
assert(type(focusBtn.props.onClick) == "function")
focusBtn.props.onClick()
assert(values.action.kind == "focus" and values.action.pane_id == "p7")
assert(panelClosedCount == 0, "the panel must wait for confirmation")
local failedSeq = values.action.seq
noctalia.state.set("actionResult", { seq = failedSeq, kind = "focus", ok = false })
assert(panelClosedCount == 0)
assert(displayed.tree.children[2].props.text == "panel_focus_failed")
focusBtn.props.onClick()
assert(values.action.seq > failedSeq)
noctalia.state.set("actionResult", { seq = failedSeq, kind = "focus", ok = true })
assert(panelClosedCount == 0, "a stale reply must not close the panel")
noctalia.state.set("actionResult", { seq = values.action.seq, kind = "focus", ok = true })
assert(panelClosedCount == 1)

onRefreshClicked()
assert(values.refresh == 2)
print("Herdr status panel fixtures passed")
