"""Model-facing tool schemas and copy, kept apart from the stdio runtime.

Everything here is static data: the closed argument contract for each pua_* tool,
its description, and the brief selector/output shapes published to a model.
"""
# Mirrors wda_controller.DEFAULT_MAX_NODES; the observe schema publishes it as the default.
DEFAULT_MAX_NODES = 200


def obj(properties,required=()):
    return {"type":"object","properties":properties,"required":list(required),"additionalProperties":False}


def string(description="",max_length=1000,enum=None):
    result={"type":"string","minLength":1,"maxLength":max_length}
    if description:result["description"]=description
    if enum:result["enum"]=enum
    return result


def num(low,high,kind="number"):
    return {"type":kind,"minimum":low,"maximum":high}


BOOL={"type":"boolean"}
SEL=obj({
 "label":string("Exact accessibility label copied from fresh nodes; real newlines and punctuation are preserved automatically.",max_length=1000),
 "label_contains":string("Substring of the label, for long or changing labels. Case-sensitive, encoded safely.",max_length=1000),
 "name":string("Exact accessibility identifier/name. Nodes omit name when it equals label.",max_length=1000),
 "value":string("Exact current accessibility value; not the text to enter. Omit values that change asynchronously.",max_length=1000),
 "type":string("Exact element type as nodes show it, e.g. Button. Not an application bundle ID.",max_length=1000),
 "enabled":{"oneOf":[{"type":"boolean"},{"type":"string","enum":["true","false"]}],"description":"Optional exact enabled filter. This does not prove hittability."},
 "index":{**num(0,199,"integer"),"description":"0-based position among the matches in tree order, as listed by pua_find or an ambiguous_target error. Only to choose between several matches."},
 "predicate":string("Advanced NSPredicate query used alone (index may accompany it). Prefer the exact fields so text is safely encoded.",max_length=2000)})
SEL["description"]="Exact label/name/value/type/enabled fields or label_contains, or a standalone predicate. rect, visible and in_viewport are observation fields, not selector fields. Matches nested at one place, or with only one on screen, resolve to that element; several separate matches return candidates with tap points and an index."
SEL["examples"]=[{"label":"返回","type":"Button"}]
SEL["minProperties"]=1
OBS=string("Post-action output, default none. Use tree/both when the next decision needs the resulting page; screenshot returns an image. This is next-step context, not proof of this action; expect/verify control verification.",enum=["none","tree","screenshot","both"])
OBS["default"]="none"
EXPECT={"expect":SEL,"observe":OBS}
VERIFY={"type":"boolean","default":False,"description":"Opt in to this operation's result check. Default false executes once and defers checking to the next required observation or final key checkpoint. Never blindly replay an uncertain mutation."}
REGION=obj({k:num(0 if k in ("x","y") else 1,10000) for k in ("x","y","width","height")},("x","y","width","height"))
REGION["description"]="Scroll rectangle in iPhone points, not screenshot pixels. observation_id is optional. Omit region for the central area, or use the actual list bounds. With verify=true, the region must fit current viewport and native modal bounds."
SCHEMAS={
 "observe":obj({"mode":string("Standalone output, default tree; actions use observe.",enum=["tree","screenshot","both"]),"include_invisible":BOOL,"max_nodes":{**num(1,500,"integer"),"default":DEFAULT_MAX_NODES},"expensive_visibility":BOOL,
     "snapshot_max_depth":{**num(1,100,"integer"),"description":"Native depth cap. Incomplete, not visible-only; tree/both only."},
     "snapshot_max_children":{**num(1,500,"integer"),"description":"Native per-parent child cap. May omit visible rows; tree/both only."},
     "prune":{"type":"boolean","description":"Prune redundant container wrappers and identical-boundary duplicates to save tokens."},"allow_stream_cache":{"type":"boolean","description":"Reuse a fresh frame from the active preview stream instead of a slow native roundtrip."}}),
 "find":obj({"selector":SEL,"limit":num(1,30,"integer")},("selector",)),
 "tap":obj({"selector":SEL,"x":num(0,10000),"y":num(0,10000),"observation_id":string("Optional ID from this Runtime. Checks app/viewport context, not whole-page pixel equality or age."),**EXPECT}),
 "swipe":obj({"direction":string("Finger movement; up usually reveals later rows. Default up.",enum=["up","down","left","right"]),"region":REGION,"observation_id":string("Optional ID from this Runtime; checks app/viewport context, not numeric/carousel text changes or age."),"expect":SEL,"verify":{**VERIFY,"description":"False: one gesture, no XML checks. True: check anchor movement once; failure returns a screenshot before another action. Numeric refresh is not progress."},"max_attempts":{**num(1,2,"integer"),"default":1,"description":"Legacy limit; even 2 stops after the first unproven gesture for screenshot inspection."},"observe":OBS}),
 "type_text":obj({"selector":SEL,"text":string("Full text to enter. Required with selector unless continue_token is given.",max_length=10000),"allow_newlines":BOOL,"submit":BOOL,"replace":BOOL,"verify":{**VERIFY,"description":"Default false enters the full intended text once without value readback. True checks exact value and stops before submit on mismatch. Secure fields require user takeover."},**EXPECT,"continue_token":string("Token from a result with input_complete=false. Pass it alone to type the rest of that text with its original options.",max_length=64)}),
 "press_button":obj({"name":string(enum=["home","volumeup","volumedown"]),"verify":VERIFY,**EXPECT},("name",)),
 "screenshot":obj({}),
 "launch_app":obj({"bundle_id":string(),"verify":VERIFY,**EXPECT},("bundle_id",)),
 "wait":obj({"selector":SEL,"timeout_seconds":num(0,20)},("selector",)),
 "scroll_find":obj({"selector":SEL,"direction":string("Finger movement; up usually reveals later rows.",enum=["up","down","left","right"]),"max_swipes":{**num(0,10,"integer"),"default":1,"description":"0 only queries; positive legacy limits allow at most one swipe, then an unresolved target returns a screenshot for the next decision."}},("selector",)),
 "collect_list":obj({"row_type":string(),"max_pages":num(1,10,"integer"),"end_selector":SEL}),
 "apps":obj({"query":string(max_length=100),"country":string(max_length=2),"source":string(enum=["auto","catalog","installed","apple"]),"limit":num(1,30,"integer")},("query",)),
 "doctor":obj({}),"ready":obj({"screenshot":{"type":"boolean","default":True,"description":"Also verify screenshot; false retains status/session/source/viewport/unlock checks."},"recover":{"type":"boolean","default":True,"description":"Normal task startup: omit or set true, so a persistent local.pid/XCTest fault can queue one bounded restart of a proven owned PUA. Use false only for an explicitly requested diagnostic/no-restart check, not a routine precheck. False is respected and returns ready=false, state=recovery_required when restart is needed; queued recovery returns state=recovering. Neither state proves readiness."}}),"metrics":obj({"reset":{"type":"boolean","default":False,"description":"Return the totals, then start a new measurement window."}}),
 "setup":obj({"action":string(enum=["discover","fetch","configure","build","start","stop","status"]),"udid":string(),"team_id":string(),"bundle_id":string(),"source_dir":string(max_length=4096),"local_port":num(1024,65535,"integer"),"device_port":num(1024,65535,"integer"),"job_id":string(),"wait_seconds":{**num(0,30),"description":"Bounded wait for this job: start defaults to 20 seconds, status to 0. Use status with job_id and 20 to await an active start/recovery. Timeout keeps the job running; do not start again."}},("action",))
}
# Each batch operation carries the same closed argument schema as its standalone tool.
BATCH_OPS=["tap","swipe","type_text","launch_app","press_button","wait","observe","scroll_find"]
SCHEMAS["batch"]=obj({"steps":{"type":"array","minItems":1,"maxItems":20,"items":{"oneOf":[obj({"op":{"type":"string","const":op},"args":SCHEMAS[op]},("op","args")) for op in BATCH_OPS]}}},("steps",))
SCHEMAS["ready"]["examples"]=[{"recover":True,"screenshot":False}]
SCHEMAS["screen"]=obj({"action":string("Default open displays the live iPhone sidebar. Pause before password/Face ID takeover; resume only after the user confirms completion.",enum=["open","pause","resume"])})
SCHEMAS["screen_frame"]=obj({"after_seq":num(0,9007199254740991,"integer"),"last_event_id":num(0,9007199254740991,"integer")})
SCHEMAS["screen_action"]=obj({
 "action":string("Preview controls: refresh, home, screenshot, refresh viewport geometry, or a user pointer tap/drag in iPhone points.",enum=["refresh","home","screenshot","tap","drag","viewport"]),
 "x":num(0,10000),"y":num(0,10000),"to_x":num(0,10000),"to_y":num(0,10000),
 "width":num(1,10000),"height":num(1,10000),"duration":num(.05,1)
},("action",))
# Tools the preview App calls itself; the model never sees them.
APP_TOOLS=("screen_frame","screen_action")
DESCRIPTIONS={
 "doctor":"Diagnose local Xcode, USB devices, signing prerequisites and PUA health without changing the phone. Start here for setup.",
 "setup":"First phone use in this chat: call setup(status) directly before READY; reuse an active start/recovery job, or start once with the existing config/build only if the service is confirmed stopped. Start waits up to 20 seconds for service readiness; if pending, query status with the same job_id and wait_seconds=20. Then READY. Missing config/source/build uses iphone-use-setup. No blanket reinstall or extra approval for authorized startup; honor no-restart instructions. Never uninstalls apps.",
 "ready":"First use: setup(status), reuse/start and wait, then READY (recover=true); only ready=true permits phone tasks. Reuse the healthy channel. pua_timeout: bounded host wait then READY again, not immediate setup/restart. pua_unreachable/not_ready: setup, not task failure. recover=true handles owned runtime faults, not cold startup. Follow recovering/recovery_required guidance. Never replay phone actions.",
 "observe":"Fresh phone tree/screenshot, point viewport and contextual observation_id. Nodes are not proven hittable. Native snapshot limits are opt-in and incomplete, not visible-only. Image pixels x image.pixel_to_point = iPhone points.",
 "find":"Query selector fields or a PUA predicate directly without a whole tree. Returns matches in tree order with index, type, texts and rect; this tool's selector documents the fields every selector accepts.",
 "tap":"Tap the element a selector resolves to after on-screen and hittable checks, or tap point coordinates with optional contextual observation_id. If the selector fails, the error returns a screenshot and tap points: tap by x/y in the next call instead of trying other selectors. Executes once optimistically; expect opts into a postcondition. Request tree/both if the next decision needs the new page.",
 "swipe":"One gesture; default verify=false/observe=none skips XML checks. verify=true checks geometry once; failure returns a screenshot even with none/tree, without another gesture. Inspect it before acting; no progress does not prove list completeness.",
 "type_text":"Enter the full intended Unicode text once into an editable nonsecure field; no test fragments. Omit selector for the focused field, including after a coordinate tap. Long input returns input_complete=false: pass only continue_token until complete; verify/submit/expect/observe run afterward. verify=true checks exact readback before submit; expect checks the page. Newlines require explicit intent; submit defaults false. Never replay uncertain input/submission.",
 "press_button":"Home uses the dedicated PUA homescreen endpoint once; default skips foreground polling. verify=true checks SpringBoard for Home, expect can check a page. Volume effects cannot be semantically verified.",
 "screenshot":"Take an iOS system screenshot into iPhone Photos; find it there or in the app's photo picker. Never replay an uncertain capture.",
 "launch_app":"Activate once using a resolved bundle ID, optimistically by default. verify=true polls foreground up to five seconds; expect checks the intended page. Request observation for the next decision. Never blindly replay uncertain activation.",
 "wait":"Bounded semantic presence polling for expected target. Presence is a UI postcondition, not proof of business correctness.",
 "batch":"Up to 20 known steps in one model round trip. Routine unverified actions continue optimistically with intermediate observe=none. Stops on actual error, failed explicit check, uncertainty, submission without an explicit result expectation, unfinished long input (input_continues) or the per-call time budget (time_budget); continue from stopped_at without repeating completed steps. Observe the last step when the next decision needs page context.",
 "scroll_find":"Find a hittable target with at most one swipe. Ambiguity/occlusion stops immediately; an unresolved post-scroll query returns a screenshot. Inspect the end, region and overlays before deciding whether to swipe again; do not blindly repeat or raise the budget.",
 "collect_list":"Collect/deduplicate accessibility rows over bounded pages. Returns evidence and explicit coverage limits; always requires reconciliation before declaring business completeness.",
 "metrics":"In-process totals without text, app data or images: PUA HTTP time and bytes, tool time, response bytes per tool, and the wait between each response and the next tool request (host, model and user time). reset=true starts a new window."
}
DESCRIPTIONS["apps"]="Resolve a real bundle ID by installed-device inventory, bundled verified aliases, or Apple's Search API. Query app name before launch instead of guessing. Store metadata does not prove installation; check installed_verified and publisher/country."
READS={"doctor","observe","find","wait","metrics","apps"}
READS.update(("screen","screen_frame"))
DESCRIPTIONS["screen"]="Open or reuse the live iPhone screen in the Codex side panel. No phone actions or UI controls. Pause the preview before password/Face ID user takeover; resume after explicit completion. READY also opens or reuses this view by default."
DESCRIPTIONS["screen_frame"]="App-only cached live preview and action cursor events. Never reads XML, starts sessions or occupies the phone operation lock."
DESCRIPTIONS["screen_action"]="App-only toolbar of the live preview, pressed by the user: refresh the preview stream, send the iPhone Home, or copy a screenshot to the Mac clipboard. Refused while the preview is paused for authentication."


def undocumented(value):
    if isinstance(value,dict):return {k:undocumented(v) for k,v in value.items() if k not in ("description","examples")}
    if isinstance(value,list):return [undocumented(v) for v in value]
    return value


# Every selector has the same fields. pua_find publishes their documentation once; other
# tools publish the same closed shape with one line pointing there.
SEL_BRIEF={**undocumented(SEL),"description":"Selector; fields as documented on pua_find.selector."}
OBS_BRIEF={**undocumented(OBS),"description":"Post-action output for the next decision; default none."}
