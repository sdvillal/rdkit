import sys
import IPython

if IPython.release.version < '0.11':
  raise ImportError('this module requires at least v0.11 of IPython')
elif IPython.release.version < '2.0':
  install_nbextension = None
  _canUse3D = False
else:
  try:
    try:
      from notebook.nbextensions import install_nbextension
      _canUse3D = True
    except ImportError:
      #  Older IPythonVersion location
      from IPython.html.nbextensions import install_nbextension
      _canUse3D = True
  except ImportError:
    # can't find notebook extensions for integrating javascript
    #  with Jupyter/IPython, disable widgets.
    _canUse3D = False
    sys.stderr.write("*" * 44)
    sys.stderr.write("\nCannot import nbextensions\n")
    sys.stderr.write("Current IPython/Jupyter version is %s\n" % IPython.release.version)
    sys.stderr.write("Disabling 3D rendering\n")
    sys.stderr.write("*" * 44)
    sys.stderr.write("\n")
    import traceback
    traceback.print_exc()

from rdkit import Chem
from rdkit.Chem import rdchem, rdChemReactions
from rdkit.Chem import Draw
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.six import BytesIO, StringIO
import copy
import os
import json
import uuid
import numpy
try:
  import Image
except ImportError:
  from PIL import Image

from IPython.display import SVG

molSize = (450, 150)
highlightSubstructs = True
kekulizeStructures = True

ipython_useSVG = False
ipython_3d = False
molSize_3d = (450, 450)
drawing_type_3d = "ball and stick"
camera_type_3d = "perspective"
shader_3d = "lambert"

# expose RDLogs to Python StdErr so they are shown
#  in the IPythonConsole not the server logs.
Chem.WrapLogs()


def _toJSON(mol):
  """For IPython notebook, renders 3D webGL objects."""

  if not ipython_3d or not mol.GetNumConformers():
    return None

  try:
    import imolecule
  except ImportError:
    raise ImportError("Cannot import 3D rendering. Please install " "with `pip install imolecule`.")

  conf = mol.GetConformer()
  if not conf.Is3D():
    return None

  mol = Chem.Mol(mol)
  try:
    Chem.Kekulize(mol)
  except Exception:
    mol = Chem.Mol(mol)
  size = molSize_3d

  # center the molecule:
  atomps = numpy.array([list(conf.GetAtomPosition(x)) for x in range(mol.GetNumAtoms())])
  avgP = numpy.average(atomps, 0)
  atomps -= avgP

  # Convert the relevant parts of the molecule into JSON for rendering
  atoms = [{"element": atom.GetSymbol(),
            "location": list(atomps[atom.GetIdx()])} for atom in mol.GetAtoms()]
  bonds = [{"atoms": [bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()],
            "order": int(bond.GetBondTypeAsDouble())} for bond in mol.GetBonds()]
  mol = {"atoms": atoms, "bonds": bonds}
  return imolecule.draw({"atoms": atoms,
                         "bonds":
                         bonds}, format="json", size=molSize_3d, drawing_type=drawing_type_3d,
                        camera_type=camera_type_3d, shader=shader_3d, display_html=False)


def _toPNG(mol):
  if hasattr(mol, '__sssAtoms'):
    highlightAtoms = mol.__sssAtoms
  else:
    highlightAtoms = []
  try:
    mol.GetAtomWithIdx(0).GetExplicitValence()
  except RuntimeError:
    mol.UpdatePropertyCache(False)

  if not hasattr(rdMolDraw2D, 'MolDraw2DCairo'):
    mc = copy.deepcopy(mol)
    try:
      img = Draw.MolToImage(mc, size=molSize, kekulize=kekulizeStructures,
                            highlightAtoms=highlightAtoms)
    except ValueError:  # <- can happen on a kekulization failure
      mc = copy.deepcopy(mol)
      img = Draw.MolToImage(mc, size=molSize, kekulize=False, highlightAtoms=highlightAtoms)
    bio = BytesIO()
    img.save(bio, format='PNG')
    return bio.getvalue()
  else:
    nmol = rdMolDraw2D.PrepareMolForDrawing(mol, kekulize=kekulizeStructures)
    d2d = rdMolDraw2D.MolDraw2DCairo(molSize[0], molSize[1])
    d2d.DrawMolecule(nmol, highlightAtoms=highlightAtoms)
    d2d.FinishDrawing()
    return d2d.GetDrawingText()


def _toSVG(mol):
  if not ipython_useSVG:
    return None
  if hasattr(mol, '__sssAtoms'):
    highlightAtoms = mol.__sssAtoms
  else:
    highlightAtoms = []
  try:
    mol.GetAtomWithIdx(0).GetExplicitValence()
  except RuntimeError:
    mol.UpdatePropertyCache(False)

  try:
    mc = rdMolDraw2D.PrepareMolForDrawing(mol, kekulize=kekulizeStructures)
  except ValueError:  # <- can happen on a kekulization failure
    mc = rdMolDraw2D.PrepareMolForDrawing(mol, kekulize=False)
  d2d = rdMolDraw2D.MolDraw2DSVG(molSize[0], molSize[1])
  d2d.DrawMolecule(mc, highlightAtoms=highlightAtoms)
  d2d.FinishDrawing()
  svg = d2d.GetDrawingText()
  return svg.replace("svg:", "")


def _toReactionPNG(rxn):
  rc = copy.deepcopy(rxn)
  img = Draw.ReactionToImage(rc, subImgSize=(int(molSize[0] / 3), molSize[1]))
  bio = BytesIO()
  img.save(bio, format='PNG')
  return bio.getvalue()


def _GetSubstructMatch(mol, query, **kwargs):
  res = mol.__GetSubstructMatch(query, **kwargs)
  if highlightSubstructs:
    mol.__sssAtoms = list(res)
  else:
    mol.__sssAtoms = []
  return res


def _GetSubstructMatches(mol, query, **kwargs):
  res = mol.__GetSubstructMatches(query, **kwargs)
  mol.__sssAtoms = []
  if highlightSubstructs:
    for entry in res:
      mol.__sssAtoms.extend(list(entry))
  return res


# code for displaying PIL images directly,
def display_pil_image(img):
  """displayhook function for PIL Images, rendered as PNG"""
  bio = BytesIO()
  img.save(bio, format='PNG')
  return bio.getvalue()


_MolsToGridImageSaved = None


def ShowMols(mols, **kwargs):
  global _MolsToGridImageSaved
  if 'useSVG' not in kwargs:
    kwargs['useSVG'] = ipython_useSVG
  if _MolsToGridImageSaved is not None:
    fn = _MolsToGridImageSaved
  else:
    fn = Draw.MolsToGridImage
  res = fn(mols, **kwargs)
  if kwargs['useSVG']:
    return SVG(res)
  else:
    return res


def InstallIPythonRenderer():
  global _MolsToGridImageSaved
  rdchem.Mol._repr_png_ = _toPNG
  rdchem.Mol._repr_svg_ = _toSVG
  if _canUse3D:
    rdchem.Mol._repr_html_ = _toJSON
  rdChemReactions.ChemicalReaction._repr_png_ = _toReactionPNG
  if not hasattr(rdchem.Mol, '__GetSubstructMatch'):
    rdchem.Mol.__GetSubstructMatch = rdchem.Mol.GetSubstructMatch
  rdchem.Mol.GetSubstructMatch = _GetSubstructMatch
  if not hasattr(rdchem.Mol, '__GetSubstructMatches'):
    rdchem.Mol.__GetSubstructMatches = rdchem.Mol.GetSubstructMatches
  rdchem.Mol.GetSubstructMatches = _GetSubstructMatches
  Image.Image._repr_png_ = display_pil_image
  _MolsToGridImageSaved = Draw.MolsToGridImage
  Draw.MolsToGridImage = ShowMols
  rdchem.Mol.__DebugMol = rdchem.Mol.Debug
  rdchem.Mol.Debug = lambda self, useStdout=False: self.__DebugMol(useStdout=useStdout)


InstallIPythonRenderer()


def UninstallIPythonRenderer():
  global _MolsToGridImageSaved
  del rdchem.Mol._repr_svg_
  del rdchem.Mol._repr_png_
  if _canUse3D:
    del rdchem.Mol._repr_html_
  del rdChemReactions.ChemicalReaction._repr_png_
  if hasattr(rdchem.Mol, '__GetSubstructMatch'):
    rdchem.Mol.GetSubstructMatch = rdchem.Mol.__GetSubstructMatch
    del rdchem.Mol.__GetSubstructMatch
  if hasattr(rdchem.Mol, '__GetSubstructMatches'):
    rdchem.Mol.GetSubstructMatches = rdchem.Mol.__GetSubstructMatches
    del rdchem.Mol.__GetSubstructMatches
  del Image.Image._repr_png_
  if _MolsToGridImageSaved is not None:
    Draw.MolsToGridImage = _MolsToGridImageSaved
  if hasattr(rdchem.Mol, '__DebugMol'):
    rdchem.Mol.Debug = rdchem.Mol.__DebugMol
    del rdchem.Mol.__DebugMol
