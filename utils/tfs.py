from __future__ import annotations
from typing import TYPE_CHECKING
import xtrack as xt
import tfs
from lhc_beam import LHCBeam


if TYPE_CHECKING:
    import pandas as pd


def twiss_to_omc3(twiss: xt.TwissTable):
    """ Convert a xsuite twiss table to an omc3-compatible tfs dataframe.

    Args:
        twiss (xt.TwissTable): xsuite twiss table

    Returns:
        tfs.TfsDataFrame (MAD-X format.)
    """
    # prepare dataframe
    df = tfs.TfsDataFrame(twiss.to_pandas())
    df = df.set_index("name", drop=True)

    # headers
    df.headers["Q1"] = twiss.qx
    df.headers["Q2"] = twiss.qy

    if twiss.dqx is not None:
        df.headers["DQ1"] = twiss.dqx
        df.headers["DQ2"] = twiss.dqy

    # rename
    df.columns = df.columns.str.upper()
    df = df.rename(columns={"LENGTH": "L"})
    df.index = df.index.str.upper()

    # filter
    index_mask = df.index.str.match("M|BPM|IP")
    columns_mask =  [col for col in LHCBeam.TWISS_COLUMNS if col in df.columns]

    return df.loc[index_mask, columns_mask]


def drop_allzero_columns(df: pd.DataFrame) -> pd.DataFrame:
    """ Drop columns that contain only zeros, to save harddrive space.

    Args:
        df (TfsDataFrame): DataFrame with all data

    Returns:
        TfsDataFrame: DataFrame with only non-zero columns.
    """
    return df.loc[:, (df != 0).any(axis="index")]
