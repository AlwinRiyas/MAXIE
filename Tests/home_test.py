"""ROADMAP 13 — home automation.

Home control is the first Phase 13 capability that touches the physical
world, so the tests lean on refusals and degradation rather than on the
happy path: an unconfigured machine must do nothing, an unknown device must
be named as unknown rather than guessed at, and a door must never unlock
because a sentence happened to contain the word "door".
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from Brain.brain_router import BrainRouter
from Brain.intent_engine import IntentEngine
from Config.config import Config
from Home.device_registry import DeviceRegistry
from Home.home_adapter import HomeAdapter
from Home.home_assistant import HomeAssistantAdapter
from Home.home_automation import HomeAutomation
from Home.hue import HueAdapter, _is_v2_id
from Security.permissions import Permissions
from Skills.home_control_skill import HomeControlSkill
from Skills.skill_manager import SkillManager
from Skills.skill_result import SkillResult
from Skills.skill_schema import SKILL_SCHEMAS

DEVICES = {
    "devices": [
        {"name": "living room light", "type": "light", "room": "living room",
         "target": "living_room_light", "aliases": ["sofa light"]},
        {"name": "porch lamp", "type": "lamp", "target": "porch_lamp"},
        {"name": "front door", "type": "lock", "target": "front_door"},
    ]
}


class _TempHome(unittest.TestCase):
    """A throwaway device store, so no test writes to the real one."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.devices_path = os.path.join(self.dir, "home_devices.json")
        self.state_path = os.path.join(self.dir, "home_state.json")
        with open(self.devices_path, "w", encoding="utf-8") as handle:
            json.dump(DEVICES, handle)
        self.registry = DeviceRegistry(self.devices_path, self.state_path)

    def adapter(self, replies=None, record=None):
        class _Adapter(HomeAdapter):
            name = "stub"

            def _dispatch(self, device, action, level=None):
                if record is not None:
                    record.append((device["name"], action, level))
                if isinstance(replies, str):
                    return replies
                return (replies or {}).get(action,
                                           f"{device['name']} is {action}.")

        return _Adapter()

    def home(self, **kwargs):
        return HomeAutomation(self.registry, self.adapter(**kwargs))


class RegistryTest(_TempHome):
    def test_devices_load_with_their_metadata(self):
        self.assertEqual(self.registry.names(),
                         ["front door", "living room light", "porch lamp"])
        device = self.registry.get("living room light")
        self.assertEqual(device["type"], "light")
        self.assertEqual(device["target"], "living_room_light")
        self.assertEqual(device["room"], "living room")

    def test_an_unknown_type_is_skipped_rather_than_guessed(self):
        """A device we cannot address is not a device."""
        path = os.path.join(self.dir, "odd.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"devices": [{"name": "teleporter", "type": "warp"}]},
                      handle)
        self.assertEqual(len(DeviceRegistry(path, self.state_path)), 0)

    def test_a_malformed_file_is_not_fatal(self):
        path = os.path.join(self.dir, "broken.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(len(DeviceRegistry(path, self.state_path)), 0)

    def test_a_missing_file_is_not_fatal(self):
        registry = DeviceRegistry(os.path.join(self.dir, "nope.json"),
                                  self.state_path)
        self.assertEqual(registry.names(), [])

    def test_exact_name_wins(self):
        self.assertEqual(self.registry.resolve("living room light")["name"],
                         "living room light")

    def test_the_phrase_resolves_with_the_article(self):
        self.assertEqual(self.registry.resolve("the living room light")
                         ["name"], "living room light")

    def test_an_alias_resolves(self):
        self.assertEqual(self.registry.resolve("turn on the sofa light")
                         ["name"], "living room light")

    def test_the_longest_match_wins(self):
        """'porch lamp' must beat a bare 'lamp' if both exist."""
        path = os.path.join(self.dir, "two.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"devices": [
                {"name": "lamp", "type": "lamp"},
                {"name": "porch lamp", "type": "lamp"},
            ]}, handle)
        registry = DeviceRegistry(path, self.state_path)
        self.assertEqual(registry.resolve("the porch lamp")["name"],
                         "porch lamp")

    def test_an_unknown_phrase_resolves_to_nothing(self):
        self.assertIsNone(self.registry.resolve("the submarine"))
        self.assertIsNone(self.registry.resolve(""))
        self.assertIsNone(self.registry.resolve(None))

    def test_state_is_recorded_and_read_back(self):
        device = self.registry.resolve("porch lamp")
        self.registry.set_state(device, "on")
        reloaded = DeviceRegistry(self.devices_path, self.state_path)
        self.assertEqual(reloaded.state["porch lamp"]["action"], "on")

    def test_toggle_uses_the_last_known_state(self):
        device = self.registry.resolve("porch lamp")
        self.assertEqual(self.registry.toggle_from(device), "on")
        self.registry.set_state(device, "on")
        self.assertEqual(self.registry.toggle_from(device), "off")
        self.registry.set_state(device, "off")
        self.assertEqual(self.registry.toggle_from(device), "on")

    def test_toggle_after_dimming_turns_it_off(self):
        """Dimming left it on, so a toggle must not turn it on again."""
        device = self.registry.resolve("porch lamp")
        self.registry.set_state(device, "set", 40)
        self.assertEqual(self.registry.toggle_from(device), "off")

    def test_an_unwritable_state_file_is_not_fatal(self):
        device = self.registry.resolve("porch lamp")
        self.registry.state_path = os.path.join(self.dir, "no", "such", "s.json")
        self.registry.set_state(device, "on")   # must not raise
        self.assertEqual(self.registry.state["porch lamp"]["action"], "on")


class HomeAutomationTest(_TempHome):
    def test_an_unconfigured_machine_does_nothing(self):
        home = HomeAutomation(self.registry, adapter=None)
        reply = home.execute("living room light", "on")
        self.assertIn("isn't set up", reply)

    def test_it_turns_a_device_on(self):
        home = self.home()
        self.assertEqual(home.execute("the living room light", "on"),
                         "living room light is on.")

    def test_it_turns_a_device_off(self):
        record = []
        home = self.home(record=record)
        home.execute("the porch lamp", "off")
        self.assertEqual(record, [("porch lamp", "off", None)])

    def test_a_successful_call_records_the_state(self):
        home = self.home()
        home.execute("the porch lamp", "on")
        self.assertEqual(self.registry.state["porch lamp"]["action"], "on")

    def test_a_failed_call_records_nothing(self):
        """Otherwise a toggle would invert from a state that never existed."""
        home = self.home(replies="The hub didn't respond.")
        home.execute("the porch lamp", "on")
        self.assertNotIn("porch lamp", self.registry.state)

    def test_an_unknown_device_is_named_and_listed(self):
        home = self.home()
        reply = home.execute("the submarine", "on")
        self.assertIn("don't know a device", reply)
        self.assertIn("porch lamp", reply)

    def test_no_devices_at_all_says_so(self):
        registry = DeviceRegistry(os.path.join(self.dir, "none.json"),
                                  self.state_path)
        home = HomeAutomation(registry, self.adapter())
        self.assertIn("don't know about any", home.execute("light", "on"))

    def test_an_unknown_action_is_refused(self):
        home = self.home()
        self.assertIn("don't know how to", home.execute("porch lamp",
                                                        "detonate"))

    def test_toggle_resolves_against_the_recorded_state(self):
        record = []
        home = self.home(record=record)
        home.execute("porch lamp", "on")
        home.execute("porch lamp", "toggle")
        self.assertEqual([action for _n, action, _l in record], ["on", "off"])

    def test_setting_a_level_passes_it_through(self):
        record = []
        home = self.home(record=record)
        home.execute("porch lamp", "set", 40)
        self.assertEqual(record, [("porch lamp", "set", 40)])

    def test_a_level_is_clamped(self):
        record = []
        home = self.home(record=record)
        home.execute("porch lamp", "set", 900)
        self.assertEqual(record[0][2], 100)

    def test_setting_without_a_level_asks(self):
        home = self.home()
        self.assertIn("What level", home.execute("porch lamp", "set"))

    def test_status_needs_no_backend_call(self):
        record = []
        home = self.home(record=record)
        reply = home.execute("porch lamp", "status")
        self.assertIn("don't know its current state", reply)
        self.assertEqual(record, [])

    def test_a_raising_backend_becomes_a_sentence(self):
        class _Broken(HomeAdapter):
            name = "broken"

            def _dispatch(self, device, action, level=None):
                raise ConnectionRefusedError("no route to host")

        home = HomeAutomation(self.registry, _Broken())
        reply = home.execute("porch lamp", "on")
        self.assertIn("didn't respond", reply)

    def test_a_slow_backend_times_out_rather_than_hanging(self):
        """A voice turn must not wait on an unreachable hub."""

        class _Slow(HomeAdapter):
            name = "slow"

            def timeout_seconds(self):
                return 0.2

            def _dispatch(self, device, action, level=None):
                import time

                time.sleep(2.0)
                return "too late"

        home = HomeAutomation(self.registry, _Slow())
        reply = home.execute("porch lamp", "on")
        self.assertIn("didn't answer in time", reply)

    def test_a_lock_needs_confirmation_even_when_asked_directly(self):
        """The skill checks the gate itself: a caller that forgets is a bug
        the user should never see the consequence of."""
        home = self.home()
        reply = home.execute("front door", "on", intent="HOME_UNLOCK")
        self.assertIn("won't unlock", reply)
        self.assertNotIn("front door", self.registry.state)

    def test_declaring_the_benign_intent_does_not_unlock_a_door(self):
        """A caller picks the intent; it does not get to pick the capability.

        "turn on the front door" is a light-shaped sentence about a lock. If
        the gate keyed on the declared intent, routing it as HOME_CONTROL
        would unlock without a confirmation.
        """
        record = []
        home = self.home(record=record)
        reply = home.execute("front door", "on", intent="HOME_CONTROL")
        self.assertIn("won't unlock", reply)
        self.assertEqual(record, [])
        self.assertNotIn("front door", self.registry.state)

    def test_toggling_a_door_is_gated_too(self):
        record = []
        home = self.home(record=record)
        self.assertIn("won't unlock",
                      home.execute("front door", "toggle"))
        self.assertEqual(record, [])

    def test_locking_a_door_is_not_gated(self):
        """Turning a lock *off* makes the house more secure, so it is not
        treated as destructive. Only the unlock direction is."""
        record = []
        home = self.home(record=record)
        self.assertIn("off", home.execute("front door", "off"))
        self.assertEqual(record, [("front door", "off", None)])

    def test_level_parsing_covers_the_phrasings(self):
        for raw, expected in ((40, 40), ("40", 40), ("40%", 40),
                              ("brightness to 40", 40),
                              ("set it to 30 percent", 30), (None, None),
                              ("no digits here", None)):
            self.assertEqual(HomeAutomation.normalise_level(raw), expected,
                             raw)


class AdapterSelectionTest(unittest.TestCase):
    def test_none_is_the_default(self):
        with mock.patch("Config.config.Config.home_config",
                        return_value={"adapter": "none"}):
            self.assertIsNone(HomeAutomation._adapter())

    def test_home_assistant_needs_a_url_and_token(self):
        for section in ({"url": "", "token": "t"},
                        {"url": "http://x", "token": ""},
                        {}):
            with mock.patch("Config.config.Config.home_config",
                            return_value={"adapter": "home_assistant",
                                          "home_assistant": section}):
                self.assertIsNone(HomeAutomation._adapter(), section)

    def test_home_assistant_is_selected_when_configured(self):
        section = {"url": "http://ha.local:8123/", "token": "abc",
                   "verify_ssl": False}
        with mock.patch("Config.config.Config.home_config",
                        return_value={"adapter": "home_assistant",
                                      "home_assistant": section}):
            adapter = HomeAutomation._adapter()
        self.assertIsInstance(adapter, HomeAssistantAdapter)
        self.assertEqual(adapter.url, "http://ha.local:8123")
        self.assertFalse(adapter.verify_ssl)

    def test_hue_is_selected_when_configured(self):
        section = {"bridge_ip": "192.168.1.5", "username": "abc"}
        with mock.patch("Config.config.Config.home_config",
                        return_value={"adapter": "hue", "hue": section}):
            adapter = HomeAutomation._adapter()
        self.assertIsInstance(adapter, HueAdapter)
        self.assertEqual(adapter.bridge_ip, "192.168.1.5")

    def test_hue_needs_both_fields(self):
        for section in ({"bridge_ip": "", "username": "u"},
                        {"bridge_ip": "1.2.3.4", "username": ""}):
            with mock.patch("Config.config.Config.home_config",
                            return_value={"adapter": "hue", "hue": section}):
                self.assertIsNone(HomeAutomation._adapter(), section)

    def test_a_base_adapter_cannot_be_constructed_into_something(self):
        self.assertIsNone(HomeAdapter.from_config())


class HomeAssistantAdapterTest(unittest.TestCase):
    def _adapter(self):
        return HomeAssistantAdapter("http://ha:8123", "secret-token",
                                    session=mock.MagicMock())

    def test_a_light_is_addressed_as_a_light(self):
        adapter = self._adapter()
        self.assertEqual(adapter._entity_id({"name": "porch lamp",
                                             "type": "lamp",
                                             "target": "porch_lamp"}),
                         "light.porch_lamp")

    def test_a_full_entity_id_is_used_verbatim(self):
        adapter = self._adapter()
        self.assertEqual(adapter._entity_id({"name": "x", "type": "light",
                                             "target": "light.kitchen"}),
                         "light.kitchen")

    def test_a_plug_is_addressed_as_a_switch(self):
        adapter = self._adapter()
        self.assertEqual(adapter._entity_id({"name": "kettle", "type": "plug",
                                             "target": "kettle"}),
                         "switch.kettle")

    def test_turning_on_posts_to_the_service_api(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        reply = adapter.call({"name": "porch lamp", "type": "lamp",
                              "target": "light.porch"}, "on")
        path, payload = adapter._post.call_args[0]
        self.assertEqual(path, "/api/services/light/turn_on")
        self.assertEqual(payload, {"entity_id": "light.porch"})
        self.assertIn("is on", reply)

    def test_turning_off_uses_turn_off(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        adapter.call({"name": "porch lamp", "type": "lamp",
                      "target": "light.porch"}, "off")
        self.assertEqual(adapter._post.call_args[0][0],
                         "/api/services/light/turn_off")

    def test_setting_a_level_sends_brightness(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        adapter.call({"name": "porch lamp", "type": "lamp",
                      "target": "light.porch"}, "set", 40)
        path, payload = adapter._post.call_args[0]
        self.assertEqual(path, "/api/services/light/turn_on")
        self.assertEqual(payload["brightness_pct"], 40)

    def test_brightness_is_clamped_by_home_assistant_too(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        adapter.call({"name": "l", "type": "light", "target": "light.l"},
                     "set", 900)
        self.assertEqual(adapter._post.call_args[0][1]["brightness_pct"], 100)

    def test_a_device_type_it_cannot_address_says_so(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        reply = adapter.call({"name": "thermostat x", "type": "unknown",
                              "target": "x"}, "on")
        self.assertIn("don't know how", reply)
        adapter._post.assert_not_called()

    def test_status_is_refused_rather_than_faked(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock()
        self.assertIn("but not report its state",
                      adapter.call({"name": "l", "type": "light",
                                    "target": "light.l"}, "status"))
        adapter._post.assert_not_called()

    def test_a_transport_failure_becomes_a_sentence(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock(
            side_effect=OSError("connection refused"))
        reply = adapter.call({"name": "l", "type": "light",
                              "target": "light.l"}, "on")
        self.assertIn("didn't respond", reply)

    def test_the_token_is_never_in_the_reply(self):
        adapter = self._adapter()
        adapter._post = mock.MagicMock(side_effect=OSError("boom secret-token"))
        self.assertNotIn("secret-token",
                         adapter.call({"name": "l", "type": "light",
                                       "target": "light.l"}, "on"))

    def test_the_session_sends_the_token_as_a_bearer_header(self):
        session = mock.MagicMock()
        adapter = HomeAssistantAdapter("http://ha:8123", "tok",
                                       session=session)
        adapter.call({"name": "l", "type": "light", "target": "light.l"},
                     "on")
        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer tok")


HUE_ID = "00000000-0000-0000-0000-000000000000"


class HueAdapterTest(unittest.TestCase):
    def test_a_36_char_target_is_used_as_the_light_id(self):
        """Hue v2 ids are 36 characters; the bridge is not asked."""
        adapter = HueAdapter("1.2.3.4", "user", opener=mock.MagicMock())
        self.assertEqual(adapter._light_id({"name": "x", "target": HUE_ID}),
                         HUE_ID)

    def test_a_light_is_found_by_name(self):
        light_id = HUE_ID
        opener = mock.MagicMock(return_value={"data": [
            {"id": "other", "metadata": {"name": "Kitchen"}},
            {"id": light_id, "metadata": {"name": "Porch"}},
        ]})
        adapter = HueAdapter("1.2.3.4", "user", opener=opener)
        self.assertEqual(adapter._light_id({"name": "Porch",
                                            "target": "Porch"}), light_id)

    def test_a_36_char_name_is_not_mistaken_for_an_id(self):
        """Length alone is not proof: a device *named* 36 characters long
        must still be looked up on the bridge."""
        # Built rather than pasted: length and dash count are the
        # properties under test, not the wording.
        name = "-".join(["lamp", "over", "x" * 8, "y" * 8, "z" * 8])
        self.assertEqual((len(name), name.count("-")), (36, 4))
        self.assertFalse(_is_v2_id(name))
        opener = mock.MagicMock(return_value={"data": [
            {"id": HUE_ID, "metadata": {"name": name}},
        ]})
        adapter = HueAdapter("1.2.3.4", "user", opener=opener)
        self.assertEqual(adapter._light_id({"name": name, "target": name}),
                         HUE_ID)
        self.assertTrue(opener.called)

    def test_an_unknown_light_says_so(self):
        opener = mock.MagicMock(return_value={"data": []})
        adapter = HueAdapter("1.2.3.4", "user", opener=opener)
        reply = adapter.call({"name": "Nook", "target": "Nook"}, "on")
        self.assertIn("couldn't find", reply)

    def test_toggle_reads_the_current_state_and_inverts_it(self):
        light_id = HUE_ID

        def _opener(url, payload, timeout):
            if payload is None and url.endswith(f"/light/{light_id}"):
                return {"data": {"on": {"on": True}}}
            return {}

        opener = mock.MagicMock(side_effect=_opener)
        adapter = HueAdapter("1.2.3.4", "user", opener=opener)
        reply = adapter.call({"name": "Porch", "target": light_id}, "toggle")
        self.assertIn("is off", reply)

    def test_status_is_refused(self):
        adapter = HueAdapter("1.2.3.4", "user", opener=mock.MagicMock())
        self.assertIn("but not report its state",
                      adapter.call({"name": "P", "target": "x"}, "status"))


class SchemaAndPermissionsTest(unittest.TestCase):
    def test_the_schema_declares_device_and_action(self):
        schema = SKILL_SCHEMAS["HOME_CONTROL"]
        self.assertEqual(schema.primary, "device")
        self.assertEqual(
            schema.validate({"device": "living room light", "action": "on"}),
            {"device": "living room light", "action": "on"})

    def test_an_unknown_action_is_rejected(self):
        schema = SKILL_SCHEMAS["HOME_CONTROL"]
        with self.assertRaises(Exception):
            schema.validate({"device": "light", "action": "detonate"})

    def test_a_missing_device_is_rejected(self):
        with self.assertRaises(Exception):
            SKILL_SCHEMAS["HOME_CONTROL"].validate({"action": "on"})

    def test_a_level_is_bounded(self):
        with self.assertRaises(Exception):
            SKILL_SCHEMAS["HOME_CONTROL"].validate(
                {"device": "light", "action": "set", "level": 500})

    def test_home_control_is_offered_but_unlock_is_not(self):
        """Offering unlock to a model invites it to try; the router refuses
        it anyway, so advertising it only spends tokens."""
        names = {tool["function"]["name"]
                 for tool in SkillManager.tool_schemas()}
        self.assertIn("HOME_CONTROL", names)
        self.assertNotIn("HOME_UNLOCK", names)

    def test_unlock_is_allowlisted_and_destructive(self):
        self.assertTrue(Permissions.can_execute("HOME_UNLOCK"))
        self.assertTrue(Permissions.requires_confirmation("HOME_UNLOCK"))
        self.assertFalse(Permissions.requires_confirmation("HOME_CONTROL"))


class IntentTest(unittest.TestCase):
    def setUp(self):
        self.engine = IntentEngine()

    def test_light_commands_are_home_control(self):
        for text in ("turn on the living room light",
                     "switch off the porch lamp",
                     "dim the bedroom light to 40",
                     "is the living room light on?"):
            self.assertEqual(self.engine.classify(text), "HOME_CONTROL", text)

    def test_unlocking_is_its_own_intent(self):
        for text in ("unlock the front door", "open the front door"):
            self.assertEqual(self.engine.classify(text), "HOME_UNLOCK", text)

    def test_a_lock_wins_over_a_light_in_the_same_sentence(self):
        self.assertEqual(
            self.engine.classify("turn off the porch light and unlock the "
                                 "back door"), "HOME_UNLOCK")

    def test_non_home_commands_are_untouched(self):
        for text, expected in (("open brave", "OPEN_APP"),
                               ("what time is it", "TIME"),
                               ("play some music", "MEDIA_PLAY_PAUSE"),
                               ("hello", "GREETING")):
            self.assertEqual(self.engine.classify(text), expected, text)

    def test_a_sentence_without_a_device_word_is_not_home(self):
        self.assertNotIn(self.engine.classify("turn on the kettle now"),
                         ("HOME_CONTROL", "HOME_UNLOCK"))

    def test_toggle_is_recognised(self):
        self.assertEqual(self.engine.classify("toggle the kitchen light"),
                         "HOME_CONTROL")


class RouterTest(_TempHome):
    """End to end through the router, with a stubbed skill."""

    def _router(self, record=None):
        router = BrainRouter()
        skill = mock.MagicMock()
        skill.execute.side_effect = lambda device, action="on", level=None, \
            intent=None: f"{device}/{action}"
        skill.status.side_effect = lambda device="": f"state of {device}"
        if record is not None:
            skill.execute.side_effect = (
                lambda device, action="on", level=None, intent=None:
                record.append((device, action, level, intent)) or "ok")
        manager = SkillManager()
        manager._skill = lambda *a, **k: skill
        router.command.skills = manager
        router.command.execute = lambda intent, value="", text=None: manager \
            .execute(intent, value, text)
        self.skill = skill
        return router

    def test_a_light_command_reaches_the_skill(self):
        record = []
        router = self._router(record)
        router.process("turn on the living room light")
        self.assertEqual(record, [("the living room light", "on", None,
                                   "HOME_CONTROL")])

    def test_a_level_is_extracted(self):
        record = []
        router = self._router(record)
        router.process("dim the living room light to 40")
        self.assertEqual(record[0][2], 40)

    def test_status_asks_the_skill_about_the_device(self):
        router = self._router()
        self.assertEqual(router.process("is the living room light on?"),
                         "state of living room light")

    def test_the_question_frame_is_stripped(self):
        router = self._router()
        self.assertEqual(router.process("what state is the porch lamp in"),
                         "state of the porch lamp")

    def test_unlocking_is_gated_by_the_router(self):
        """SEC-11's gate is keyed on capability, so the new intent inherits
        it without any new code."""
        record = []
        router = self._router(record)
        reply = router.process("unlock the front door")
        self.assertIn("won't unlock", reply)
        self.assertEqual(record, [])

    def test_the_confirmation_is_a_separate_turn(self):
        record = []
        router = self._router(record)
        router.process("unlock the front door")
        router.process("yes")
        self.assertEqual(len(record), 1)
        self.assertEqual(record[0][3], "HOME_UNLOCK")

    def test_a_turn_naming_no_device_asks_which_one(self):
        record = []
        router = self._router(record)
        reply = router._home_dispatch("HOME_CONTROL", "", "turn on the")
        self.assertIn("Which device", reply)
        self.assertEqual(record, [])

    def test_a_bare_device_word_is_passed_on_for_the_skill_to_resolve(self):
        """The router has no registry; "the light" is the skill's to reject,
        and it names what it does know rather than guessing."""
        record = []
        router = self._router(record)
        self.assertEqual(router.process("turn on the light"), "ok")
        self.assertEqual(record[0][0], "the light")

    def test_the_router_never_dispatches_a_home_action_in_controlled_mode_by_accident(self):
        """Home control is deterministic: no model proposal is involved."""
        record = []
        router = self._router(record)
        router.routing_mode = "controlled"
        router.process("turn on the living room light")
        self.assertEqual(len(record), 1)


class CompensatingActionTest(_TempHome):
    """12.9: rollback used to be a surface with nothing behind it. These
    cases are the first skill that actually declares an undo."""

    def _skill(self, record=None):
        return HomeControlSkill(self.home(record=record))

    def test_turning_a_light_on_can_be_undone(self):
        result = self._skill().execute_result(device="living room light",
                                              action="on")
        self.assertTrue(result.ok)
        self.assertEqual(result.undo, ("HOME_CONTROL",
                                       {"device": "living room light",
                                        "action": "off"}))

    def test_turning_a_light_off_can_be_undone(self):
        result = self._skill().execute_result(device="living room light",
                                              action="off")
        self.assertEqual(result.undo[1]["action"], "on")

    def test_a_failed_call_declares_no_compensation(self):
        """Nothing changed, so there is nothing to revert -- claiming an
        undo here would run a second call against a device we never touched."""
        skill = HomeControlSkill(self.home(replies="The hub didn't respond."))
        result = skill.execute_result(device="living room light", action="on")
        self.assertIsNone(result.undo)

    def test_a_dim_declares_no_compensation(self):
        """Restoring "the level we just read" is not restoring the state the
        failure interrupted. Saying nothing is the honest answer.

        The stub answers "is on", so this asserts the *absence* of a
        compensation rather than passing because the call happened to fail.
        """
        skill = HomeControlSkill(self.home(
            replies={"set": "living room light is on."}))
        result = skill.execute_result(device="living room light", action="set",
                                      level=40)
        self.assertTrue(result.ok)
        self.assertIsNone(result.undo)

    def test_a_device_that_does_not_resolve_declares_no_compensation(self):
        result = self._skill().execute_result(device="the submarine",
                                              action="on")
        self.assertIsNone(result.undo)

    def test_a_door_is_never_compensated(self):
        """Putting a lock back the way a plan found it, unasked, is a
        second state change dressed up as a rollback.

        Checked on the decision itself: through `execute_result` the
        confirmation gate refuses first, which would make this pass without
        the lock rule being what stopped it.
        """
        skill = self._skill()
        door = self.registry.resolve("front door")
        self.assertIsNone(skill._compensating(door, None, "on"))
        self.assertIsNone(skill._compensating(door, {"action": "off"},
                                              "off"))

    def test_the_compensation_validates_against_the_schema(self):
        """An undo hook that the schema would reject fails at rollback time
        and is reported as partial, so it must be schema-clean now."""
        result = self._skill().execute_result(device="living room light",
                                              action="on")
        self.assertEqual(
            SKILL_SCHEMAS["HOME_CONTROL"].validate(result.undo[1]),
            result.undo[1])

    def test_the_compensation_is_allowlisted_and_ungated(self):
        skill, arguments = self._skill().execute_result(
            device="living room light", action="on").undo
        self.assertTrue(Permissions.can_execute(skill))
        self.assertFalse(Permissions.requires_confirmation(skill))

    def test_an_executor_rollback_really_turns_the_light_back_off(self):
        """End to end: a plan step that fails, with a real home skill, must
        leave the device as the plan found it."""
        from Logs.logger import Logger
        from Skills.agent_executor import AgentExecutor

        calls = []
        manager = SkillManager()
        manager._skill = lambda *a, **k: self._skill(record=calls)
        executor = AgentExecutor(manager, Logger.instance())

        results = [self._skill(record=calls).execute_result(
            device="living room light", action="on"),
            SkillResult.failure("HOME_CONTROL", "the hub didn't respond")]
        outcome = executor.rollback(results)

        self.assertEqual(outcome["reverted"], ["HOME_CONTROL"])
        self.assertTrue(outcome["complete"])
        self.assertEqual([action for _name, action, _level in calls],
                         ["on", "off"])
        self.assertEqual(self.registry.state["living room light"]["action"],
                         "off")

    def test_prior_state_is_none_before_we_ever_touch_a_device(self):
        device = self.registry.resolve("porch lamp")
        self.assertIsNone(self.home().prior_state(device))
        self.home().execute("porch lamp", "on")
        self.assertEqual(
            self.home().prior_state(self.registry.resolve("porch lamp")),
            {"action": "on"})


class StructuredDispatchTest(_TempHome):
    def _manager(self):
        manager = SkillManager()
        manager._skill = lambda *a, **k: HomeControlSkill(self.home())
        return manager

    def test_a_structured_intent_returns_a_skill_result(self):
        result = self._manager().execute_args(
            "HOME_CONTROL", {"device": "living room light", "action": "on"})
        self.assertIsInstance(result, SkillResult)
        self.assertTrue(result.ok)

    def test_an_unstructured_intent_still_returns_a_string(self):
        reply = self._manager().execute_args("CALCULATE", {"expression": "2+2"})
        self.assertIsInstance(reply, str)

    def test_execute_structured_returns_none_for_an_unstructured_intent(self):
        self.assertIsNone(
            self._manager().execute_structured("CALCULATE", {"x": 1}))

    def test_the_plain_path_is_unchanged(self):
        """A voice turn must still get a sentence, not a dataclass."""
        reply = self._manager().execute("HOME_CONTROL", "living room light",
                                        {"action": "on"})
        self.assertIsInstance(reply, str)

    def test_a_rejected_argument_never_reaches_the_skill(self):
        reply = self._manager().execute_args("HOME_CONTROL",
                                             {"device": "x", "action": "nuke"})
        self.assertIsInstance(reply, str)
        self.assertIn("clearer", reply)


class ConfigTest(unittest.TestCase):
    def test_the_default_adapter_is_none(self):
        self.assertEqual(Config.DEFAULT_SYSTEM["home"]["adapter"], "none")
        self.assertEqual(Config.DEFAULT_SYSTEM["home"]["hue"]["username"], "")

    def test_the_timeout_is_bounded(self):
        for bad in (0.0, 60):
            with self.assertRaises(Exception):
                Config.validate({"system": {"home": {"timeout_seconds":
                                                      bad}}})

    def test_a_reasonable_timeout_is_accepted(self):
        data = Config.validate({"system": {"home": {"timeout_seconds": "2"}}})
        self.assertEqual(data["system"]["home"]["timeout_seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()