"""Profile edits cannot be overwritten by a deletion snapshot."""
import asyncio
from types import SimpleNamespace

from test_ev_vehicle_config_deletion import deletion


def test_post_waits_for_delete_and_preserves_other_profile_edit(deletion):
    async def scenario():
        view, profiles, store, _ = deletion('byd_device')
        view._hass.config_entries = SimpleNamespace(async_entries=lambda domain: [])
        entered, release = asyncio.Event(), asyncio.Event()
        original = store.async_save

        async def delayed(data):
            entered.set()
            await release.wait()
            await original(data)

        async def body():
            return {'vehicle_id': 'other', 'display_name': 'Updated'}

        store.async_save = delayed
        delete = asyncio.create_task(view.delete(SimpleNamespace(query={'vehicle_id': 'byd_device'})))
        await asyncio.wait_for(entered.wait(), 2)
        post = asyncio.create_task(view.post(SimpleNamespace(json=body)))
        await asyncio.sleep(0.05)
        assert not post.done()
        release.set()
        assert (await delete).status == 200
        result = await asyncio.wait_for(post, 2)
        assert result.status == 200, result.body
        assert profiles.saved['vehicle_charging_configs'][0]['display_name'] == 'Updated'
        assert [c['vehicle_id'] for c in profiles.saved['vehicle_charging_configs']] == ['other']

    asyncio.run(scenario())
