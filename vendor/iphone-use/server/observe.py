"""Observation layer: phone tree/screenshot to what the model receives.

Split out of the controller so the model-facing shape, the freshness rules and
the image path can be read (and tested) without the gesture and input code.
"""
import base64
import datetime as dt
from pathlib import Path
import time
import uuid

from actions import default_region

from constants import DEFAULT_MAX_NODES, VIEWPORT_TTL
from primitives import fail, finite, integer, stale
from tree import compact_node, prune_nodes, tree_digest
import wda_image


class ObservationMixin:
    def remember(self,nodes,viewport,app,has_tree=True):
        ident=uuid.uuid4().hex[:12]
        self.snapshots[ident]={"time":time.monotonic(),"viewport":viewport,"app":app,"nodes":nodes if has_tree else None}
        while len(self.snapshots)>32:
            self.snapshots.popitem(last=False)
        return ident


    def observe(self,mode="tree",include_invisible=False,max_nodes=DEFAULT_MAX_NODES,expensive_visibility=False,snapshot_max_depth=None,snapshot_max_children=None,prune=True,allow_stream_cache=True):
        if mode not in ("tree","screenshot","both"):
            fail("invalid_argument","mode must be tree, screenshot or both.")
        integer(max_nodes,"max_nodes",1,500)
        limits={}
        for value,key,maximum in ((snapshot_max_depth,"snapshotMaxDepth",100),(snapshot_max_children,"snapshotMaxChildren",500)):
            if value is not None:limits[key]=integer(value,key,1,maximum)
        if limits and mode=="screenshot":
            fail("invalid_argument","Snapshot limits require tree or both mode.",action_executed=False)
        if mode=="screenshot":
            app=self.active_app()
            nodes,viewport=[],self.viewport(VIEWPORT_TTL)
        else:
            nodes,viewport=(self.bounded_tree(include_invisible,expensive_visibility,limits) if limits
                            else self.tree(include_invisible,expensive_visibility))
            app=self._source_app or self.active_app()
        if prune and nodes:
            nodes=prune_nodes(nodes)
        self._observed_digest=tree_digest([compact_node(node) for node in nodes])
        result=self.observation_from_state(nodes,viewport,app,mode,max_nodes,expensive_visibility,pruned=prune,allow_stream_cache=allow_stream_cache)
        if limits:
            result.update(snapshot_limits=limits,tree_complete=False,truncated=True,total_nodes_scope="bounded_snapshot")
            result.setdefault("warnings",[]).append("Native depth/child limits apply before snapshot creation, not by visible area. Controls or visible rows may be omitted; missing nodes do not prove absence or list completeness. Inspect a screenshot.")
        return result


    def observation_from_state(self,nodes,viewport,app,mode,max_nodes=DEFAULT_MAX_NODES,expensive_visibility=False,pruned=False,allow_stream_cache=True):
        result={"observation_id":self.remember(nodes,viewport,app,has_tree=mode!="screenshot"),
                "observed_at":dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"app":app,"viewport":viewport}
        if mode in ("tree","both"):
            result.update({"nodes":[compact_node(node) for node in nodes[:max_nodes]],"total_nodes":len(nodes),"truncated":len(nodes)>max_nodes})
            if expensive_visibility:result["visibility_computed"]=True
            if pruned:result["pruned"]=True
            if not nodes:
                result["warnings"]=["Empty accessibility tree: inspect a screenshot for lock, iPhone Mirroring conflict, loading, or custom-rendered content before acting."]
        if mode in ("screenshot","both"):
            result["image"]=self.capture(viewport,allow_cached_stream=allow_stream_cache)
        return result


    def capture(self,viewport,allow_cached_stream=True):
        """Native PNG kept as evidence; the model receives a bounded image with its exact point scale.
        When a live stream is running, reuses the fresh cached frame to avoid a slow roundtrip."""
        if allow_cached_stream and getattr(self, "screen", None):
            try:
                recent = self.screen.recent_frame(max_age_seconds=0.8)
                if recent and recent.get("jpeg"):
                    artifacts=self.state_dir/"artifacts";artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
                    dest=artifacts/(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]+".jpg")
                    dest.write_bytes(recent["jpeg"]);dest.chmod(0o600)
                    width, height = recent.get("width") or 0, recent.get("height") or 0
                    if width and height and (width>height)!=(viewport["width"]>viewport["height"]):
                        viewport.update(self.viewport())
                    for pattern in ("*.png","*.jpg"):
                        for old in sorted(artifacts.glob(pattern))[:-100]:
                            old.unlink()
                    image={"path":str(dest),"mimeType":"image/jpeg","cached_stream":True}
                    if width and height:
                        image.update(width=width,height=height,pixel_to_point=[round(viewport["width"]/width,4),round(viewport["height"]/height,4)])
                    return image
            except Exception:
                pass

        encoded=self.client.request("GET","/screenshot").get("value")
        try:
            data=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError) as exc:
            fail("invalid_response", "Invalid screenshot encoding.")
        if not data.startswith(wda_image.PNG_SIGNATURE):
            fail("invalid_response","PUA screenshot is not PNG.")
        artifacts=self.state_dir/"artifacts";artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
        # Stage the multi-megabyte native PNG outside the retained folder: only the
        # image actually handed to the model is kept (the JPEG normally, the PNG when
        # the capture is already small or conversion is unavailable).
        staging=self.state_dir/"tmp";staging.mkdir(mode=0o700,parents=True,exist_ok=True)
        stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]
        staged=staging/(stamp+".png")
        staged.write_bytes(data);staged.chmod(0o600)
        native=wda_image.png_size(data[:32])
        if native and (native[0]>native[1])!=(viewport["width"]>viewport["height"]):
            # The capture is turned the other way than the remembered viewport: the phone rotated.
            viewport.update(self.viewport())
        try:
            produced,mime,width,height=wda_image.model_image(staged)
            produced=Path(produced)
            dest=artifacts/(stamp+produced.suffix)
            produced.replace(dest)
        finally:
            try:
                if staged.exists():
                    staged.unlink()
            except OSError:
                pass
        path=dest
        for pattern in ("*.png","*.jpg"):
            for old in sorted(artifacts.glob(pattern))[:-100]:
                old.unlink()
        image={"path":str(path),"mimeType":mime}
        if width and height:
            image.update(width=width,height=height,pixel_to_point=[round(viewport["width"]/width,4),round(viewport["height"]/height,4)])
        return image


    def snapshot(self,observation_id):
        old=self.snapshots.get(observation_id)
        if not old:
            stale("This observation is unknown to the current Runtime. Observe again or use current viewport coordinates.","unknown_observation")
        if self.active_app()!=old["app"]:
            stale("The foreground app changed. Observe again.","foreground_changed")
        return old


    def guard(self,observation_id=None):
        old=self.snapshot(observation_id) if observation_id is not None else None
        # A supplied ID asks for a context check, so read the viewport again for it.
        viewport=self.viewport(0 if old else VIEWPORT_TTL)
        if old and viewport!=old["viewport"]:
            stale("Orientation or viewport changed. Observe again before using the earlier coordinates.","viewport_changed")
        return viewport


    def guard_region(self,observation_id,region):
        viewport=self.guard(observation_id)
        self.region(region,viewport)
        return viewport


    def region(self,region,viewport):
        if region is None:
            return default_region(viewport)
        if not isinstance(region,dict) or set(region)!={"x","y","width","height"}:
            fail("invalid_argument","region must have x/y/width/height in iPhone points.")
        for k,v in region.items():finite(v,k,0 if k in ("x","y") else 1)
        if region["x"]+region["width"]>viewport["width"] or region["y"]+region["height"]>viewport["height"]:
            fail("invalid_argument","Gesture region is outside viewport.")
        return region


    def native_modals(self,nodes):
        return [{k:n[k] for k in ("type","name","label","rect") if k in n} for n in nodes if n["type"] in ("XCUIElementTypeAlert","XCUIElementTypeSheet")]


    @staticmethod
    def modal_report(modals):
        return [compact_node(modal) for modal in modals]


    def scroll_observation(self,nodes,viewport,mode,max_nodes=DEFAULT_MAX_NODES):
        if mode=="none":return None
        # The caller already read the complete tree and viewport. Reuse both;
        # adding a screenshot does not require another viewport/XML request.
        return self.observation_from_state(nodes,viewport,self._source_app or self.active_app(),mode,max_nodes)


    def observe_after(self,mode,max_nodes=DEFAULT_MAX_NODES):
        """Observe after an action without a fixed sleep.

        A blind wait costs 0.5s on every step and still guesses. Read after a short
        head start instead and, while tree mode can judge it, keep the reading that
        differs from the pre-action tree: a changed tree is the transition being
        observed, an unchanged one means the UI has not started moving yet."""
        budget = min(self.settle_seconds, 0.5)
        if budget <= 0 or mode not in ("tree","both","screenshot"):
            return self.observe(mode,max_nodes=max_nodes)
        started = time.monotonic()
        leave = min(0.12, budget)
        if leave > 0:
            time.sleep(leave)
        result = self.observe(mode,max_nodes=max_nodes)
        if mode == "screenshot":
            return result
        # At most one confirmation read: a changed tree already is the transition,
        # and an unchanged one only earns a second look, not a polling loop.
        if self._pre_action_digest is not None and time.monotonic() - started < budget:
            if tree_digest(result.get("nodes")) == self._pre_action_digest:
                time.sleep(min(0.1, max(0.0, budget - (time.monotonic() - started))))
                result = self.observe(mode,max_nodes=max_nodes)
        self._pre_action_digest = self._observed_digest
        return result
