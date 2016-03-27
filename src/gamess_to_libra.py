#*********************************************************************************
#* Copyright (C) 2016 Kosuke Sato, Alexey V. Akimov
#* 
#* This file is distributed under the terms of the GNU General Public License
#* as published by the Free Software Foundation, either version 2 of
#* the License, or (at your option) any later version.
#* See the file LICENSE in the root directory of this distribution
#* or <http://www.gnu.org/licenses/>.
#*
#*********************************************************************************/

## \file gamess_to_libra.py 
# This module implements the functions that extract parameters from the gamess output file:
# atomic forces , molecular energies, molecular orbitals, and atomic basis information.
# The forces are used for simulating Classical MD on Libra 
# and the others for calculating time-averaged energies and Non-Adiabatic Couplings(NACs).



from detect import *
from extract import *
from ao_basis import *
from overlap import *
from Ene_NAC import *
#from reduce_matrix import *
from moment import *

import os
import sys
import math

# First, we add the location of the library to test to the PYTHON path
sys.path.insert(1,os.environ["libra_mmath_path"])
sys.path.insert(1,os.environ["libra_qchem_path"])
sys.path.insert(1,os.environ["libra_hamiltonian_path"] + "/Hamiltonian_Atomistic/Hamiltonian_QM/Control_Parameters")


#print "\nTest 1: Importing the library and its content"
from libmmath import *
from libqchem import *
from libcontrol_parameters import *


def unpack_file(filename,flag):
    ##
    # Finds the keywords and their patterns and extracts the parameters
    # \param[in] filename  GAMESS output file name
    # \param[in] flag      a flag for debugging unpack_file module
    # This function returns the data extracted from the file, in the form of dictionary :
    # atomic basis sets, molecular energies, molecular coefficients, gradients, respectively.
    #
    # Used in:  main.py/main
    #           main.py/main/nve_MD/gamess_to_libra

    f_gam = open(filename,"r")
    l_gam = f_gam.readlines()
    f_gam.close()

    data = {}

    # detect the columns showing parameters
    detect(l_gam,data,flag)    

    # extract the parameters from the columns detected
    extract(l_gam,data,flag)

    # Construct the AO basis
    data["ao_basis"] = ao_basis(data,flag) 

    return data["ao_basis"], data["E"], data["C"], data["gradient"], data



def reduce_matrix(M,min_shift,max_shift,HOMO_indx):
    ##
    # Extracts a sub-matrix M_sub of the original matrix M. The size of the extracted matrix is
    # controlled by the input parameters
    # \param[in] M The original input matrix
    # \param[in] min_shift - is the index defining the minimal orbital in the active space
    # to consider. This means that the lowest 1-electron state will be HOMO_indx + min_shift.
    # \param[in] max_shift - is the index defining the maximal orbital in the active space
    # to consider. This means that the highest 1-electron state will be HOMO_indx + max_shift.
    # \param[in] HOMO_indx - the index of the HOMO orbital (indexing starts from 0)
    # Example: if we have C2H4 system - 12 valence electrons, so 6 orbitals are occupied:
    # occ = [0,1,2,3,4,5] and lets say 4 more states unoccupied virt = [6,7,8,9] Then if we
    # use HOMO_indx = 5, min_shift = -2, max_shift = 2 will reduce the active space to the
    # orbitals [3,4,5,  6,7], where orbitals 3,4,5 are occupied and 6,7 are unoccupied.
    # So we reduce the initial 10 x 10 matrix to the 5 x 5 matrix
    # This function returns the reduced matrix "M_red".
    #
    # Used in: main.py/main/run_MD/gamess_to_libra


    if(HOMO_indx+min_shift<0):
        print "Error in reduce_matrix: The min_shift/HOMO_index combination result in the out-of-range error for the reduced matrix\nExiting..."
        sys.exit(0)

    sz = max_shift - min_shift + 1
    if(sz>M.num_of_cols):
        print "Error in reduce_matrix: The size of the cropped matrix is larger than the size of the original matrix\nExiting..."
        sys.exit(0)

    M_red = MATRIX(sz,sz)
    pop_submatrix(M,M_red,range(HOMO_indx+min_shift,HOMO_indx+max_shift+1))


    return M_red




def gamess_to_libra(params, ao, E, C, suff):
    ## 
    # Finds the keywords and their patterns and extracts the parameters
    # \param[in] params :  contains input parameters , in the directory form
    # \param[in,out] ao :  atomic orbital basis at "t" old
    # \param[in,out] E  :  molecular energies at "t" old
    # \param[in,out] C  :  molecular coefficients at "t" old
    # \param[in] suff : The suffix to add to the name of the output files
    # this suffix is now considered to be of a string type - so you can actually encode both the
    # iteration number (MD timestep), the nuclear cofiguration (e.g. trajectory), and any other
    # related information
    #
    # This function outputs the files for excited electron dynamics
    # in "res" directory.
    # It returns the forces which act on the atoms.
    # Also, it returns new atomic orbitals, molecular energies, and
    # molecular coefficients used for calculating time-averaged
    # molecular energies and Non-Adiabatic Couplings(NACs).
    #
    # Used in: main.py/nve_MD/

    # 2-nd file - time "t+dt"  new
    ao2, E2, C2, Grad, data = unpack_file(params["gms_out"],params["debug_gms_unpack"])

    # calculate overlap matrix of atomic and molecular orbitals
    P11, P22, P12, P21 = overlap(ao,ao2,C,C2,params["basis_option"])

    # calculate transition dipole moment matrices in the MO basis:
    # mu_x = <i|x|j>, mu_y = <i|y|j>, mu_z = <i|z|j>
    # this is done for the "current" state only    
    mu_x, mu_y, mu_z = transition_dipole_moments(ao2,C2)
    data["mu_x"] = mu_x
    data["mu_y"] = mu_y
    data["mu_z"] = mu_z

    if params["debug_mu_output"]==1:
        print "mu_x:";    mu_x.show_matrix()
        print "mu_y:";    mu_y.show_matrix()
        print "mu_z:";    mu_z.show_matrix()
 
    if params["debug_densmat_output"]==1:
        print "P11 and P22 matrixes should show orthogonality"
        print "P11 is";    P11.show_matrix()
        print "P22 is";    P22.show_matrix()
        print "P12 and P21 matrixes show overlap of MOs for different molecular geometries "
        print "P12 is";    P12.show_matrix()
        print "P21 is";    P21.show_matrix()


    ### TO DO: In the following section, we need to avoid computing NAC matrices in the full
    # basis. We will need the information on cropping, in order to avoid computations that 
    # we do not need (the results are discarded anyways)
    # calculate molecular energies and Non-Adiabatic Couplings(NACs) on MO basis
    E_mol = average_E(E,E2)
    D_mol = NAC(P12,P21,params["dt_nucl"])

    # reduce the matrix size
    E_mol_red = reduce_matrix(E_mol,params["min_shift"], params["max_shift"],params["HOMO"])
    D_mol_red = reduce_matrix(D_mol,params["min_shift"], params["max_shift"],params["HOMO"])
    ### END TO DO

    if params["print_mo_ham"]==1:
        E_mol.show_matrix(params["mo_ham"] + "full_re_Ham_" + suff)
        D_mol.show_matrix(params["mo_ham"] + "full_im_Ham_" + suff)
        E_mol_red.show_matrix(params["mo_ham"] + "reduced_re_Ham_" + suff)
        D_mol_red.show_matrix(params["mo_ham"] + "reduced_im_Ham_" + suff)

    # store "t+dt"(new) parameters on "t"(old) ones
    for i in range(0,len(ao2)):
        ao[i] = AO(ao2[i])
    E = MATRIX(E2)
    C = MATRIX(C2)

    # Returned data:
    # Grad: Grad[k][i] - i-th projection of the gradient w.r.t. to k-th nucleus (i = 0, 1, 2)
    # data: a dictionary containing various data, such as transition dipole moments, AOs, etc
    # E_mol: the matrix of the 1-el orbital energies in the full space of the orbitals
    # D_mol: the matrix of the NACs computed with 1-el orbitals. Same dimension as E_mol
    # E_mol_red: the matrix of the 1-el orbital energies in the reduced (active) space
    # D_mol_red: the matrix of the NACs computed with 1-el orbital. Same dimension as E_mol_red

    return Grad, data, E_mol, D_mol, E_mol_red, D_mol_red
