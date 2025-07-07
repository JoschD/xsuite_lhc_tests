"""
Setup a cpymad MAD-X simulation for the LHC machine.

The base class ``LHCBeam`` is defined to contain machine parameters,
a bit similar to the Accelerator-Class in omc3.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
import xpart as xp


#Dataclasses -------------------------------------------------------------

@dataclass()
class LHC:
    """ Dataclass for the LHC accelerator.

    Should be replaced with the accelerator class, if xsuite is implemented into omc3.
    """
    year: str
    model_dir: Path
    modifiers: list[str | Path] = None
    nat_tunes: tuple[float, float] = (62.28, 60.31)
    energy: float | int = 6800
    chroma: float | int  = 3
    emittance_norm: float | tuple[float, float] = 2.5e-6  # normalized emittance, or tuple for x,y
    n_particles: float = 1.5e11   # number of particles in beam
    acc_models_link: Path = Path('acc-models-lhc')
    # Constants
    ACCEL: ClassVar[str] = 'lhc'
    TWISS_COLUMNS: ClassVar[Sequence[str]] = tuple(
        ['NAME', 'KEYWORD', 'S', 'X', 'Y', 'L', 'LRAD',
        'BETX', 'BETY', 'ALFX', 'ALFY',
        'DX', 'DY', 'MUX', 'MUY',
        'R11', 'R12', 'R21', 'R22'] + [f"K{i:d}{s:s}L" for i in range(0, 8) for s in ("", "S")]
    )

    # Init ---

    def __post_init__(self):
        """ Setup the MADX, output dirs and logging as well as additional instance parameters. """
        self.model_dir.mkdir(exist_ok=True, parents=True)

        self._create_symlink()
        self._find_modifiers()

        try:
            self.emittance = self.emittance_norm[0] * xp.PROTON_MASS_EV / self.energy, self.emittance_norm[1] * xp.PROTON_MASS_EV / self.energy
        except TypeError:
            self.emittance = [self.emittance_norm * xp.PROTON_MASS_EV / self.energy, self.emittance_norm * xp.PROTON_MASS_EV / self.energy] * 2

        self.rel_energy_spread = 4.5e-4*(450./self.energy)**0.5

    def _create_symlink(self):
        """ Creates a symbolic link to the acc-models-lhc directory. """
        acc_models_lhc = Path("/afs/cern.ch/eng/acc-models/lhc/")
        full_link = self.model_dir / self.acc_models_link
        if full_link.is_symlink():
            full_link.unlink()
        full_link.symlink_to(acc_models_lhc / self.year)

    def _find_modifiers(self):
        """ Go through the modifiers and check if they are
        a) given as a full path
        b) in the output directory
        c) in the optics-directory of acc-models-lhc

        The found path is then assigned to the modifiers list, in the cases
        b) and c) relative to the outputdir, as MAD-X is running in there
        as current working directory.
        """
        if self.modifiers is None:
            self.modifiers = []
        else:
            new_modifiers = []
            for modifier in self.modifiers:
                sources = (
                    Path(modifier).absolute(),  # overrides the 'self.outputdir' below
                    modifier,
                    self.acc_models_link / "operation" / "optics" / modifier
                )
                for modifier_path in sources:
                    if (self.model_dir / modifier_path).is_file():
                        new_modifiers.append(modifier_path)
                        break
                else:
                    raise FileNotFoundError(f"Could not find modifier {modifier} in {sources}")

            self.modifiers = new_modifiers

    @staticmethod
    def get_sequence_file_for_beam(beam: int):
        if beam == 4:
            return "lhcb4.seq"
        return "lhc.seq"

    @staticmethod
    def get_sequence_for_beam(beam: int):
        if beam == 4:
            return "lhcb2"
        return f"lhcb{beam}"


@dataclass()
class LHCBeam(LHC):
    """ Same as above, but for a single beam. """
    beam: int = 1

    # Output Helper ---

    def output_path(self, type_: str, output_id: str, dir_: Path | None = None, suffix: str = ".tfs") -> Path:
        """ Returns the output path for standardized tfs names in the default output directory.

        Args:
            type_ (str): Type of the output file (e.g. 'twiss', 'errors', 'ampdet')
            output_id (str): Name of the output (e.g. 'nominal')
            dir_ (Path): Override default directory.
            suffix (str): suffix of the output file.

        Returns:
            Path: Path to the output file
         """
        if dir_ is None:
            dir_ = self.model_dir
        return dir_ / f'{type_}.lhc.b{self.beam:d}.{output_id}{suffix}'

    @property
    def cycling_element(self):
        """ First element after injection for each beam. """
        if self.beam == 1:
            return "MSIA.EXIT.B1"
        return "MKI.A5R8.B2"

    @property
    def other_beam(self):
        return 1 if self.beam in (2, 4) else 2

    @property
    def bv(self):
        return -1 if self.beam == 2 else 1

    @property
    def sequence(self):
        return self.get_sequence_for_beam(self.beam)

    @property
    def sequence_file(self):
        return self.get_sequence_file_for_beam(self.beam)
