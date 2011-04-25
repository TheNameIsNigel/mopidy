from pykka.actor import ThreadingActor
from pykka.registry import ActorRegistry

from mopidy.mixers.base import BaseMixer
from mopidy.outputs.base import BaseOutput

class GStreamerSoftwareMixer(ThreadingActor, BaseMixer):
    """Mixer which uses GStreamer to control volume in software."""

    def __init__(self):
        self.output = None

    def on_start(self):
        output_refs = ActorRegistry.get_by_class(BaseOutput)
        assert len(output_refs) == 1, 'Expected exactly one running output.'
        self.output = output_refs[0].proxy()

    def _get_volume(self):
        return self.output.get_volume().get()

    def _set_volume(self, volume):
        self.output.set_volume(volume).get()
