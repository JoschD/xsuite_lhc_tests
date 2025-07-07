from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import xtrack as xt

from utils.logging import disable_logging

if TYPE_CHECKING:
    from lhc_beam import LHCBeam


LOGGER = logging.getLogger(__name__)


def match(beam: LHCBeam, line: xt.Line, step: float = 1e-8,  tolerance: float = 1e-10, chroma: bool = False):
    """ Match the line to the natural tunes and chroma stored in the beam-object.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line to be matched
        step (float, optional): step size for the optimization. Defaults to 1e-8.
        tolerance (float, optional): tolerance for the optimization. Defaults to 1e-10.
        chroma (bool, optional): whether to match chroma. Defaults to False.
    """
    LOGGER.info("Matching line to natural tunes" + "" if not chroma else " and chroma")
    tune_knob = "dq{plane}.b{beam}_op"
    chroma_knob = "dqp{plane}.b{beam}_op"

    vary=[xt.Vary(name=tune_knob.format(beam=beam.beam, plane=plane), step=step) for plane in "xy"]
    targets=[xt.TargetSet(qx=beam.nat_tunes[0], qy=beam.nat_tunes[1], tol=tolerance)]
    if chroma:
        vary.append(xt.Vary(name=chroma_knob.format(beam=beam.beam, plane=plane), step=step) for plane in "xy")
        targets.append(xt.TargetSet(dqx=beam.chroma, dqy=beam.chroma, tol=tolerance))

    with disable_logging():
        opt = line.match(vary=vary, targets=targets)
        # opt.assert_within_tol=False
        opt.solve()