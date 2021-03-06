"""
Library for doing sequence design that can be expressed as linear algebra
operations for rapid processing by numpy (e.g., generating all DNA sequences
of a certain length and calculating all their full duplex binding energies
in the nearest neighbor model and filtering those outside a given range).

Based on the DNA single-stranded tile (SST) sequence designer used in the following publication.

"Diverse and robust molecular algorithms using reprogrammable DNA self-assembly"
Woods\*, Doty\*, Myhrvold, Hui, Zhou, Yin, Winfree. (\*Joint first co-authors)
"""  # noqa

# from __future__ import annotations

from typing import Tuple, List, Collection, Optional, Union, Sequence, Dict
from dataclasses import dataclass
import math
import itertools as it
from functools import lru_cache

import numpy as np

default_rng: np.random.Generator = np.random.default_rng()  # noqa

bits2base = ['A', 'C', 'G', 'T']
base2bits = {'A': 0b00, 'C': 0b01, 'G': 0b10, 'T': 0b11,
             'a': 0b00, 'c': 0b01, 'g': 0b10, 't': 0b11}


def idx2seq(idx: int, length: int) -> str:
    """Return the lexicographic idx'th DNA sequence of given length."""
    seq = ['x'] * length
    for i in range(length - 1, -1, -1):
        seq[i] = bits2base[idx & 0b11]
        idx >>= 2
    return ''.join(seq)


def seq2arr(seq: str) -> np.ndarray:
    """Convert seq (string with DNA alphabet) to numpy array with integers 0,1,2,3."""
    return np.array([base2bits[base] for base in seq], dtype=np.ubyte)


def seqs2arr(seqs: Sequence[str]) -> np.ndarray:
    """Return numpy 2D array converting the given DNA sequences to integers."""
    if len(seqs) == 0:
        return np.empty((0, 0), dtype=np.ubyte)
    seq_len = len(seqs[0])
    for seq in seqs:
        if len(seq) != seq_len:
            raise ValueError('All sequences in seqs must be equal length')
    num_seqs = len(seqs)
    arr = np.empty((num_seqs, seq_len), dtype=np.ubyte)
    for i in range(num_seqs):
        arr[i] = [base2bits[base] for base in seqs[i]]
    return arr


def arr2seq(arr: np.ndarray) -> str:
    bases_ch = [bits2base[base] for base in arr]
    return ''.join(bases_ch)


def make_array_with_all_dna_seqs(length: int, bases: Collection[str] = ('A', 'C', 'G', 'T')) -> np.ndarray:
    """Return 2D numpy array with all DNA sequences of given length in
    lexicographic order. Bases contains bases to be used: ('A','C','G','T') by
    default, but can be set to a subset of these.

    Uses the encoding described in the documentation for DNASeqList. The result
    is a 2D array, where each row represents a DNA sequence, and that row
    has one byte per base."""

    if not set(bases) <= {'A', 'C', 'G', 'T'}:
        raise ValueError(f"bases must be a subset of {'A', 'C', 'G', 'T'}; cannot be {bases}")
    if len(bases) == 0:
        raise ValueError('bases cannot be empty')

    num_bases = len(bases)
    num_seqs = num_bases ** length

    #     shift = np.arange(2*(length-1), -1, -2)
    #     nums = np.repeat(np.arange(numseqs), length)
    #     nums2D = nums.reshape([numseqs, length])
    #     shifts = np.tile(0b11 << shift, numseqs)
    #     shifts2D = shifts.reshape([numseqs, length])
    #     arr = (shifts2D & nums2D) >> shift

    # the former code took up too much memory (using int32 or int64)
    # the following code makes sure it's 1 byte per base
    powers_num_bases = [num_bases ** k for k in range(length)]
    #         bases = np.array([_base2bits['A'], _base2bits['C'], _base2bits['G'], _base2bits['T']], dtype=np.ubyte)
    base_bits = [base2bits[base] for base in bases]
    bases = np.array(base_bits, dtype=np.ubyte)

    list_of_arrays = False
    if list_of_arrays:
        # this one seems to be faster but takes more memory, probably because just before the last command
        # there are two copies of the array in memory at once
        columns = []
        for i, j, c in zip(reversed(powers_num_bases), powers_num_bases, list(range(length))):
            columns.append(np.tile(np.repeat(bases, i), j))
        arr = np.vstack(columns).transpose()
    else:
        # this seems to be slightly slower but takes less memory, since it
        # allocates only the final array, plus one extra column of that
        # array at a time
        arr = np.empty((num_seqs, length), dtype=np.ubyte)
        for i, j, c in zip(reversed(powers_num_bases), powers_num_bases, list(range(length))):
            arr[:, c] = np.tile(np.repeat(bases, i), j)

    return arr


def make_array_with_random_subset_of_dna_seqs(length: int, num_seqs: int,
                                              rng: np.random.Generator,
                                              bases: Collection[str] = ('A', 'C', 'G', 'T')) -> np.ndarray:
    """
    Return 2D numpy array with random subset of size `num_seqs` of DNA sequences of given length.
    Bases contains bases to be used: ('A','C','G','T') by default, but can be set to a subset of these.

    Uses the encoding described in the documentation for DNASeqList. The result is a 2D array,
    where each row represents a DNA sequence, and that row has one byte per base.

    :param length: length of each row
    :param num_seqs: number of rows
    :param bases: DNA bases to use
    :param rng: numpy random number generator (type returned by numpy.random.default_rng())
    :return: 2D numpy array with random subset of size `num_seqs` of DNA sequences of given length
    """
    if not set(bases) <= {'A', 'C', 'G', 'T'}:
        raise ValueError(f"bases must be a subset of {'A', 'C', 'G', 'T'}; cannot be {bases}")
    if len(bases) == 0:
        raise ValueError('bases cannot be empty')
    elif len(bases) == 1:
        raise ValueError('bases must have at least two elements')

    base_bits = np.array([base2bits[base] for base in bases], dtype=np.ubyte)

    arr = rng.choice(a=base_bits, size=(num_seqs, length))
    unique_sorted_arr = np.unique(arr, axis=0)

    return unique_sorted_arr


# @lru_cache(maxsize=10000000)
def longest_common_substring(a1: np.ndarray, a2: np.ndarray, vectorized: bool = True) -> Tuple[int, int, int]:
    """Return start and end indices (a1start, a2start, length) of longest common
    substring (subarray) of 1D arrays a1 and a2."""
    assert len(a1.shape) == 1
    assert len(a2.shape) == 1
    counter = np.zeros(shape=(len(a1) + 1, len(a2) + 1), dtype=np.int)
    a1idx_longest = a2idx_longest = -1
    len_longest = 0

    if vectorized:
        for i1 in range(len(a1)):
            idx = (a2 == a1[i1])
            idx_shifted = np.hstack([[False], idx])
            counter[i1 + 1, idx_shifted] = counter[i1, idx] + 1
        idx_longest = np.unravel_index(np.argmax(counter), counter.shape)
        if idx_longest[0] > 0:
            len_longest = counter[idx_longest]
            a1idx_longest = int(idx_longest[0] - len_longest)
            a2idx_longest = int(idx_longest[1] - len_longest)
    else:
        for i1 in range(len(a1)):
            for i2 in range(len(a2)):
                if a1[i1] == a2[i2]:
                    c = counter[i1, i2] + 1
                    counter[i1 + 1, i2 + 1] = c
                    if c > len_longest:
                        len_longest = c
                        a1idx_longest = i1 + 1 - c
                        a2idx_longest = i2 + 1 - c
    return a1idx_longest, a2idx_longest, len_longest


# @lru_cache(maxsize=10000000)
def longest_common_substrings_singlea1(a1: np.ndarray, a2s: np.ndarray) \
        -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return start and end indices (a1starts, a2starts, lengths) of longest common
    substring (subarray) of 1D array a1 and rows of 2D array a2s.

    If length[i]=0, then a1starts[i]=a2starts[i]=0 (not -1), so be sure to check
    length[i] to see if any substrings actually matched."""
    assert len(a1.shape) == 1
    assert len(a2s.shape) == 2
    numa2s = a2s.shape[0]
    len_a1 = len(a1)
    len_a2 = a2s.shape[1]
    counter = np.zeros(shape=(len_a1 + 1, numa2s, len_a2 + 1), dtype=np.int)

    for i1 in range(len(a1)):
        idx = (a2s == a1[i1])
        idx_shifted = np.insert(idx, 0, np.zeros(numa2s, dtype=np.bool), axis=1)
        counter[i1 + 1, idx_shifted] = counter[i1, idx] + 1

    counter = np.swapaxes(counter, 0, 1)

    counter_flat = counter.reshape(numa2s, (len_a1 + 1) * (len_a2 + 1))
    idx_longest_raveled = np.argmax(counter_flat, axis=1)
    len_longest = counter_flat[np.arange(counter_flat.shape[0]), idx_longest_raveled]

    idx_longest = np.unravel_index(idx_longest_raveled, dims=(len_a1 + 1, len_a2 + 1))
    a1idx_longest = idx_longest[0] - len_longest
    a2idx_longest = idx_longest[1] - len_longest

    return a1idx_longest, a2idx_longest, len_longest


# @lru_cache(maxsize=10000000)
def longest_common_substrings_product(a1s: np.ndarray, a2s: np.ndarray) \
        -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return start and end indices (a1starts, a2starts, lengths) of longest common
    substring (subarray) of each pair in the cross product of rows of a1s and a2s.

    If length[i]=0, then a1starts[i]=a2starts[i]=0 (not -1), so be sure to check
    length[i] to see if any substrings actually matched."""
    numa1s = a1s.shape[0]
    numa2s = a2s.shape[0]
    a1s_cp = np.repeat(a1s, numa2s, axis=0)
    a2s_cp = np.tile(a2s, (numa1s, 1))

    a1idx_longest, a2idx_longest, len_longest = _longest_common_substrings_pairs(a1s_cp, a2s_cp)

    a1idx_longest = a1idx_longest.reshape(numa1s, numa2s)
    a2idx_longest = a2idx_longest.reshape(numa1s, numa2s)
    len_longest = len_longest.reshape(numa1s, numa2s)

    return a1idx_longest, a2idx_longest, len_longest


def pair_index(n: int) -> np.ndarray:
    index = np.fromiter(it.chain.from_iterable(it.combinations(range(n), 2)), int, count=n * (n - 1))
    return index.reshape(-1, 2)


def _longest_common_substrings_pairs(a1s: np.ndarray, a2s: np.ndarray) \
        -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    assert len(a1s.shape) == 2
    assert len(a2s.shape) == 2
    assert a1s.shape[0] == a2s.shape[0]

    numpairs = a1s.shape[0]

    len_a1 = a1s.shape[1]
    len_a2 = a2s.shape[1]

    counter = np.zeros(shape=(len_a1 + 1, numpairs, len_a2 + 1), dtype=np.int)

    for i1 in range(len_a1):
        a1s_cp_col = a1s[:, i1].reshape(numpairs, 1)
        a1s_cp_col_rp = np.repeat(a1s_cp_col, len_a2, axis=1)

        idx = (a2s == a1s_cp_col_rp)
        idx_shifted = np.hstack([np.zeros(shape=(numpairs, 1), dtype=np.bool), idx])
        counter[i1 + 1, idx_shifted] = counter[i1, idx] + 1

    counter = np.swapaxes(counter, 0, 1)

    counter_flat = counter.reshape(numpairs, (len_a1 + 1) * (len_a2 + 1))
    idx_longest_raveled = np.argmax(counter_flat, axis=1)
    len_longest = counter_flat[np.arange(counter_flat.shape[0]), idx_longest_raveled]

    idx_longest = np.unravel_index(idx_longest_raveled, dims=(len_a1 + 1, len_a2 + 1))
    a1idx_longest = idx_longest[0] - len_longest
    a2idx_longest = idx_longest[1] - len_longest

    return a1idx_longest, a2idx_longest, len_longest


def longest_common_substrings_all_pairs_strings(seqs1: Sequence[str], seqs2: Sequence[str]) \
        -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For Python strings"""
    a1s = seqs2arr(seqs1)
    a2s = seqs2arr(seqs2)
    return _longest_common_substrings_pairs(a1s, a2s)


def _strongest_common_substrings_all_pairs_return_energies_and_counter(
        a1s: np.ndarray, a2s: np.ndarray, temperature: float) \
        -> Tuple[np.ndarray, np.ndarray]:
    assert len(a1s.shape) == 2
    assert len(a2s.shape) == 2
    assert a1s.shape[0] == a2s.shape[0]

    numpairs = a1s.shape[0]
    len_a1 = a1s.shape[1]
    len_a2 = a2s.shape[1]
    counter = np.zeros(shape=(len_a1 + 1, numpairs, len_a2 + 1), dtype=np.int)
    energies = np.zeros(shape=(len_a1 + 1, numpairs, len_a2 + 1), dtype=np.float)

    #     if not loop_energies:
    loop_energies = calculate_loop_energies(temperature)

    prev_match_shifted_idxs = None

    for i1 in range(len_a1):
        a1s_col = a1s[:, i1].reshape(numpairs, 1)
        a1s_col_rp = np.repeat(a1s_col, len_a2, axis=1)

        # find matching chars and extend length of substring
        match_idxs = (a2s == a1s_col_rp)
        match_shifted_idxs = np.hstack([np.zeros(shape=(numpairs, 1), dtype=np.bool), match_idxs])
        counter[i1 + 1, match_shifted_idxs] = counter[i1, match_idxs] + 1

        if i1 > 0:
            # calculate energy if matching substring has length > 1
            prev_bases = a1s[:, i1 - 1]
            cur_bases = a1s[:, i1]
            loops = (prev_bases << 2) + cur_bases
            latest_energies = loop_energies[loops].reshape(numpairs, 1)
            latest_energies_rp = np.repeat(latest_energies, len_a2, axis=1)
            match_idxs_false_at_end = np.hstack([match_idxs, np.zeros(shape=(numpairs, 1), dtype=np.bool)])
            both_match_idxs = match_idxs_false_at_end & prev_match_shifted_idxs
            prev_match_shifted_shifted_idxs = np.hstack(
                [np.zeros(shape=(numpairs, 1), dtype=np.bool), prev_match_shifted_idxs])[:, :-1]
            both_match_shifted_idxs = match_shifted_idxs & prev_match_shifted_shifted_idxs
            energies[i1 + 1, both_match_shifted_idxs] = energies[i1, both_match_idxs] + latest_energies_rp[
                both_match_idxs]

        #         prev_match_idxs = match_idxs
        prev_match_shifted_idxs = match_shifted_idxs

    counter = counter.swapaxes(0, 1)
    energies = energies.swapaxes(0, 1)

    return counter, energies


def internal_loop_penalty(n: int, temperature: float) -> float:
    return 1.5 + (2.5 * 0.002 * temperature * math.log(1 + n))


def _strongest_common_substrings_all_pairs(a1s: np.ndarray, a2s: np.ndarray, temperature: float) \
        -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    numpairs = a1s.shape[0]
    len_a1 = a1s.shape[1]
    len_a2 = a2s.shape[1]

    counter, energies = _strongest_common_substrings_all_pairs_return_energies_and_counter(a1s, a2s,
                                                                                           temperature)

    counter_flat = counter.reshape(numpairs, (len_a1 + 1) * (len_a2 + 1))
    energies_flat = energies.reshape(numpairs, (len_a1 + 1) * (len_a2 + 1))

    idx_strongest_raveled = np.argmax(energies_flat, axis=1)
    len_strongest = counter_flat[np.arange(counter_flat.shape[0]), idx_strongest_raveled]
    energy_strongest = energies_flat[np.arange(counter_flat.shape[0]), idx_strongest_raveled]

    idx_strongest = np.unravel_index(idx_strongest_raveled, dims=(len_a1 + 1, len_a2 + 1))
    a1idx_strongest = idx_strongest[0] - len_strongest
    a2idx_strongest = idx_strongest[1] - len_strongest

    return a1idx_strongest, a2idx_strongest, len_strongest, energy_strongest


def strongest_common_substrings_all_pairs_string(seqs1: Sequence[str], seqs2: Sequence[str],
                                                 temperature: float) \
        -> Tuple[List[float], List[float], List[float], List[float]]:
    """For Python strings representing DNA; checks for reverse complement matches
    rather than direct matches, and evaluates nearest neighbor energy, returning
    indices lengths, and energies of strongest complementary substrings."""
    a1s = seqs2arr(seqs1)
    a2s = seqs2arr(seqs2)
    a1idx_strongest, a2idx_strongest, len_strongest, energy_strongest = _strongest_common_substrings_all_pairs(
        a1s,
        wc_arr(a2s),
        temperature)
    return list(a1idx_strongest), list(a2idx_strongest), list(len_strongest), list(energy_strongest)


def energies_strongest_common_substrings(seqs1: Sequence[str], seqs2: Sequence[str], temperature: float) \
        -> List[float]:
    a1s = seqs2arr(seqs1)
    a2s = seqs2arr(seqs2)
    a1idx_strongest, a2idx_strongest, len_strongest, energy_strongest = \
        _strongest_common_substrings_all_pairs(a1s, wc_arr(a2s), temperature)
    return list(energy_strongest)


@dataclass
class DNASeqList:
    """
    Represents a list of DNA sequences of identical length. The sequences are stored as a 2D numpy array
    of bytes :py:data:`DNASeqList.seqarr`. Each byte represents a single DNA base (so it is not a compact
    representation; the most significant 6 bits of the byte will always be 0).
    """

    seqarr: np.ndarray
    """
    Uses a (noncompact) internal representation using 8 bits (1 byte, dtype = np.ubyte) per base,
    stored in a numpy 2D array of bytes.
    Each row (axis 0) is a DNA sequence, and each column (axis 1) is a base in a sequence.
    
    The code used is :math:`A \\to 0, C \\to 1, G \\to 2, T \\to 3`.
    """

    numseqs: int
    """Number of DNA sequences (number of rows, axis 0, in :py:data:`DNASeqList.seqarr`)"""

    seqlen: int
    """Length of each DNA sequence (number of columns, axis 1, in :py:data:`DNASeqList.seqarr`)"""

    rng: np.random.Generator
    """Random number generator to use."""

    def __init__(self,
                 length: Optional[int] = None,
                 num_random_seqs: Optional[int] = None,
                 shuffle: bool = False,
                 alphabet: Collection[str] = ('A', 'C', 'G', 'T'),
                 seqs: Optional[Sequence[str]] = None,
                 seqarr: np.ndarray = None,
                 filename: Optional[str] = None,
                 rng: np.random.Generator = default_rng):
        """
        Creates a set of DNA sequences, all of the same length.

        Create either all sequences of a given length if seqs is not specified,
        or all sequences in seqs if seqs is specified. If neither is specified
        then all sequences of length 3 are created.

        *Exactly one* of the following should be specified:

        - `length` (possibly along with `alphabet` and `num_random_seqs`)

        - `seqs`

        - `seqarr`

        - `filename`

        :param length: length of sequences; `num_seqs` and `alphabet` can also be specified along with it
        :param num_random_seqs: number of sequences to generate; if not specified, then all sequences
                                of length `length` using bases from `alphabet` are generated
        :param shuffle: whether to shuffle sequences
        :param alphabet: alphabet; must be a subset of {'A', 'C', 'G', 'T'}
        :param seqs: sequence (e.g., list or tuple) of strings, all of the same length
        :param seqarr: 2D NumPy array, with axis 0 moving between sequences,
                       and axis 1 moving between consecutive DNA bases in a sequence
        :param filename: name of file containing a :any:`DNASeqList`
                         as written by :py:meth:`DNASeqList.write_to_file`
        :param rng: numpy random number generator (type returned by numpy.random.default_rng())
        """
        for v1, v2 in it.combinations([length, seqs, seqarr, filename], 2):
            if v1 is not None and v2 is not None:
                raise ValueError('exactly one of length, seqs, seqarra, or filename can be non-None')
        self.rng = rng
        if seqarr is not None:
            self.seqarr = seqarr
            self.numseqs, self.seqlen = seqarr.shape
        elif seqs is not None:
            if len(seqs) == 0:
                raise ValueError('seqs must have positive length')
            self.seqlen = len(seqs[0])
            for seq in seqs:
                if len(seq) != self.seqlen:
                    raise ValueError('All sequences in seqs must be equal length')
            self.numseqs = len(seqs)
            self.seqarr = seqs2arr(seqs)
        elif filename is not None:
            self._read_from_file(filename)
        elif length is not None:
            self.seqlen = length
            if num_random_seqs is None:
                self.seqarr = make_array_with_all_dna_seqs(self.seqlen, alphabet)
            else:
                self.seqarr = make_array_with_random_subset_of_dna_seqs(
                    self.seqlen, num_random_seqs, self.rng, alphabet)
            self.numseqs = len(self.seqarr)
        else:
            raise ValueError('at least one of length, seqs, seqarr, or filename must be specified')

        self.shift = np.arange(2 * (self.seqlen - 1), -1, -2)

        if shuffle:
            self.shuffle()

    def __len__(self) -> int:
        return self.numseqs

    def __contains__(self, seq: str) -> bool:
        if len(seq) != self.seqlen:
            return False
        arr = seq2arr(seq)
        return np.any(~np.any(self.seqarr - arr, 1))

    def _read_from_file(self, filename: str) -> None:
        """Reads from fileName in the format defined in writeToFile.
        Only meant to be called from constructor."""
        with open(filename, 'r+') as f:
            first_line = f.readline()
            num_seqs_str, seq_len_str, temperature = first_line.split()
            self.numseqs = int(num_seqs_str)
            self.seqlen = int(seq_len_str)
            self.seqarr = np.empty((self.numseqs, self.seqlen), dtype=np.ubyte)
            for i in range(self.numseqs):
                line = f.readline()
                seq = line.strip()
                self.seqarr[i] = [base2bits[base] for base in seq]

    def write_to_file(self, filename: str) -> None:
        """Writes text file describing DNA sequence list, in format

        numseqs seqlen
        seq1
        seq2
        seq3
        ...

        where numseqs, seqlen are integers, and seq1,
        ... are strings from {A,C,G,T}"""
        with open(filename, 'w+') as f:
            f.write(str(self.numseqs) + ' ' + str(self.seqlen) + '\n')
            for i in range(self.numseqs):
                f.write(self.get_seq_str(i) + '\n')

    def wcenergy(self, idx: int, temperature: float) -> float:
        """Return energy of idx'th sequence binding to its complement."""
        return wcenergy(self.seqarr[idx], temperature)

    def __repr__(self) -> str:
        return 'DNASeqSet(seqs={})'.format(str([self[i] for i in range(self.numseqs)]))

    def __str__(self) -> str:
        if self.numseqs <= 64:
            ret = [self.get_seq_str(i) for i in range(self.numseqs)]
            return ','.join(ret)
        else:
            ret = [self.get_seq_str(i) for i in range(3)] + ['...'] + \
                  [self.get_seq_str(i) for i in range(self.numseqs - 3, self.numseqs)]
            return ','.join(ret)

    def shuffle(self) -> None:
        self.rng.shuffle(self.seqarr)

    def to_list(self) -> List[str]:
        """Return list of strings representing the sequences, e.g. ['ACG','TAA']"""
        return [self.get_seq_str(idx) for idx in range(self.numseqs)]

    def get_seq_str(self, idx: int) -> str:
        """Return idx'th DNA sequence as a string."""
        return arr2seq(self.seqarr[idx])

    def get_seqs_str_list(self, slice_: slice) -> List[str]:
        """Return a list of strings specified by slice."""
        bases_lst = self.seqarr[slice_]
        ret = []
        for bases in bases_lst:
            bases_ch = [bits2base[base] for base in bases]
            ret.append(''.join(bases_ch))
        return ret

    def __getitem__(self, slice_: Union[int, slice]) -> Union[str, List[str]]:
        if isinstance(slice_, int):
            return self.get_seq_str(slice_)
        elif isinstance(slice_, slice):
            return self.get_seqs_str_list(slice_)
        else:
            raise ValueError('idx must be int or slice')

    def pop(self) -> str:
        """Remove and return last seq, as a string."""
        seq_str = self.get_seq_str(-1)
        self.seqarr = np.delete(self.seqarr, -1, 0)
        self.numseqs -= 1
        return seq_str

    def pop_array(self) -> np.ndarray:
        """Remove and return last seq, as a string."""
        arr = self.seqarr[-1]
        self.seqarr = np.delete(self.seqarr, -1, 0)
        self.numseqs -= 1
        return arr

    def append_seq(self, newseq: str) -> None:
        self.append_arr(seq2arr(newseq))

    def append_arr(self, newarr: np.ndarray) -> None:
        self.seqarr = np.vstack([self.seqarr, newarr])
        self.numseqs += 1

    def filter_hamming(self, threshold: int) -> None:
        seq = self.pop_array()
        arr_keep = np.array([seq])
        self.shuffle()
        while self.seqarr.shape[0] > 0:
            seq = self.pop_array()
            while self.seqarr.shape[0] > 0:
                hamming_min = np.min(np.sum(np.bitwise_xor(arr_keep, seq) != 0, axis=1))
                too_close = (hamming_min < threshold)
                if not too_close:
                    break
                seq = self.pop_array()
            arr_keep = np.vstack([arr_keep, seq])
        self.seqarr = arr_keep
        self.numseqs = self.seqarr.shape[0]

    def hamming_min(self, arr: np.ndarray) -> int:
        """Returns minimum Hamming distance between arr and any sequence in
        this DNASeqList."""
        distances = np.sum(np.bitwise_xor(self.seqarr, arr) != 0, axis=1)
        return np.min(distances)

    # remove quotes when Py3.6 support dropped
    def filter_energy(self, low: float, high: float, temperature: float) -> 'DNASeqList':
        """Return new DNASeqList with seqs whose wc complement energy is within
        the given range."""
        wcenergies = calculate_wc_energies(self.seqarr, temperature)
        within_range = (low <= wcenergies) & (wcenergies <= high)
        new_seqarr = self.seqarr[within_range]
        return DNASeqList(seqarr=new_seqarr)

    def energies(self, temperature: float) -> np.ndarray:
        wcenergies = calculate_wc_energies(self.seqarr, temperature)
        return wcenergies

    # def filter_PF(self, low, high, temperature):
    #     '''Return new DNASeqList with seqs whose wc complement energy is within
    #     the given range, according to NUPACK.'''
    #     raise NotImplementedError('this was assuming energies get stored, which no longer is the case')
    #     pfenergies = np.zeros(self.wcenergies.shape)
    #     i = 0
    #     print('searching through %d sequences for PF energies' % self.numseqs)
    #     for seq in self.toList():
    #         energy = sst_dsd.duplex(seq, temperature)
    #         pfenergies[i] = energy
    #         i += 1
    #         if i % 100 == 0:
    #             print('searched %d so far' % i)
    #     within_range = (low <= pfenergies) & (pfenergies <= high)
    #     new_seqarr = self.seqarr[within_range]
    #     return DNASeqList(seqarr=new_seqarr)

    # remove quotes when Py3.6 support dropped
    def filter_end_gc(self) -> 'DNASeqList':
        """Remove any sequence with A or T on the end. Also remove domains that
        do not have an A or T either next to that base, or one away. Otherwise
        we could get a domain ending in {C,G}^3, which, placed next to any
        domain ending in C or G, will create a substring in {C,G}^4 and be
        rejected if we are filtering those."""
        left = self.seqarr[:, 0]
        right = self.seqarr[:, -1]
        left_p1 = self.seqarr[:, 1]
        left_p2 = self.seqarr[:, 2]
        right_m1 = self.seqarr[:, -2]
        right_m2 = self.seqarr[:, -3]
        abits = base2bits['A']
        cbits = base2bits['C']
        gbits = base2bits['G']
        tbits = base2bits['T']
        good = (((left == cbits) | (left == gbits)) & ((right == cbits) | (right == gbits)) &
                ((left_p1 == abits) | (left_p1 == tbits) | (left_p2 == abits) | (left_p2 == tbits)) &
                ((right_m1 == abits) | (right_m1 == tbits) | (right_m2 == abits) | (right_m2 == tbits)))
        seqarrpass = self.seqarr[good]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_end_at(self, gc_near_end: bool = False) -> 'DNASeqList':
        """Remove any sequence with C or G on the end. Also, if gc_near_end is True,
        remove domains that do not have an C or G either next to that base,
        or one away, to prevent breathing."""
        left = self.seqarr[:, 0]
        right = self.seqarr[:, -1]
        abits = base2bits['A']
        tbits = base2bits['T']
        good = ((left == abits) | (left == tbits)) & ((right == abits) | (right == tbits))
        if gc_near_end:
            cbits = base2bits['C']
            gbits = base2bits['G']
            left_p1 = self.seqarr[:, 1]
            left_p2 = self.seqarr[:, 2]
            right_m1 = self.seqarr[:, -2]
            right_m2 = self.seqarr[:, -3]
            good = (good &
                    ((left_p1 == cbits) | (left_p1 == gbits) | (left_p2 == cbits) | (left_p2 == gbits)) &
                    ((right_m1 == cbits) | (right_m1 == gbits) | (right_m2 == cbits) | (right_m2 == gbits)))
        seqarrpass = self.seqarr[good]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_base_nowhere(self, base: str) -> 'DNASeqList':
        """Remove any sequence that has given base anywhere."""
        good = (self.seqarr != base2bits[base]).all(axis=1)
        seqarrpass = self.seqarr[good]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_base_count(self, base: str, low: int, high: int) -> 'DNASeqList':
        """Remove any sequence not satisfying low <= #base <= high."""
        sumarr = np.sum(self.seqarr == base2bits[base], axis=1)
        good = (low <= sumarr) & (sumarr <= high)
        seqarrpass = self.seqarr[good]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_base_at_pos(self, pos: int, base: str) -> 'DNASeqList':
        """Remove any sequence that does not have given base at position pos."""
        mid = self.seqarr[:, pos]
        good = (mid == base2bits[base])
        seqarrpass = self.seqarr[good]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_substring(self, subs: Sequence[str]) -> 'DNASeqList':
        """Remove any sequence with any elements from subs as a substring."""
        if len(set([len(sub) for sub in subs])) != 1:
            raise ValueError('All substrings in subs must be equal length: %s' % subs)
        sublen = len(subs[0])
        subints = [[base2bits[base] for base in sub] for sub in subs]
        powarr = [4 ** k for k in range(sublen)]
        subvals = np.dot(subints, powarr)
        toeplitz = create_toeplitz(self.seqlen, sublen)
        convolution = np.dot(toeplitz, self.seqarr.transpose())
        passall = np.ones(self.numseqs, dtype=np.bool)
        for subval in subvals:
            passsub = np.all(convolution != subval, axis=0)
            passall = passall & passsub
        seqarrpass = self.seqarr[passall]
        return DNASeqList(seqarr=seqarrpass)

    # remove quotes when Py3.6 support dropped
    def filter_seqs_by_g_quad(self) -> 'DNASeqList':
        """Removes any sticky ends with 4 G's in a row (a G-quadruplex)."""
        return self.filter_substring(['GGGG'])

    # remove quotes when Py3.6 support dropped
    def filter_seqs_by_g_quad_c_quad(self) -> 'DNASeqList':
        """Removes any sticky ends with 4 G's or C's in a row (a quadruplex)."""
        return self.filter_substring(['GGGG', 'CCCC'])


def create_toeplitz(seqlen: int, sublen: int) -> np.ndarray:
    """Creates a toeplitz matrix, useful for finding subsequences.

    seqlen is length of larger sequence; sublen is length of substring we're checking for."""
    powarr = [4 ** k for k in range(sublen)]
    # if _SCIPY_AVAIL:
    #     import scipy.linalg as linalg
    #     toeplitz = linalg.toeplitz([1] + [0] * (seqlen - sublen),
    #                                powarr + [0] * (seqlen - sublen))
    # else:
    rows = seqlen - (sublen - 1)
    cols = seqlen
    toeplitz = np.zeros((rows, cols), dtype=np.int)
    toeplitz[:, 0:sublen] = [powarr] * rows
    shift = list(range(rows))
    for i in range(rows):
        toeplitz[i] = np.roll(toeplitz[i], shift[i])
    return toeplitz


@lru_cache(maxsize=32)
def calculate_loop_energies(temperature: float, negate: bool = False) -> np.ndarray:
    """Get SantaLucia and Hicks nearest-neighbor loop energies for given temperature,
    1 M Na+. """
    energies = (_dH - (temperature + 273.15) * _dS / 1000.0)
    if negate:
        energies = -energies
    return energies
    # SantaLucia & Hicks' values are in cal/mol/K for dS, and kcal/mol for dH.
    # Here we divide dS by 1000 to get the RHS term into units of kcal/mol/K
    # which gives an overall dG in units of kcal/mol.
    # One reason we want dG to be in units of kcal/mol is to
    # give reasonable/readable numbers close to 0 for dG(Assembly).
    # The reason we might want to flip the sign is that, by convention, in the kTAM, G_se
    # (which is computed from the usually negative dG here) is usually positive.


# _dH and _dS come from Table 1 in SantaLucia and Hicks, Annu Rev Biophys Biomol Struct. 2004;33:415-40.
#                 AA    AC    AG    AT    CA    CC     CG    CT
_dH = np.array([-7.6, -8.4, -7.8, -7.2, -8.5, -8.0, -10.6, -7.8,
                # GA    GC    GG    GT    TA    TC    TG    TT
                -8.2, -9.8, -8.0, -8.4, -7.2, -8.2, -8.5, -7.6],
               dtype=np.float32)

#                  AA     AC     AG     AT     CA     CC     CG     CT
_dS = np.array([-21.3, -22.4, -21.0, -20.4, -22.7, -19.9, -27.2, -21.0,
                #  GA     GC     GG     GT     TA     TC     TG     TT
                -22.2, -24.4, -19.9, -22.4, -21.3, -22.2, -22.7, -21.3],
               dtype=np.float32)

#  AA  AC  AG  AT  CA  CC  CG  CT  GA  GC  GG  GT  TA  TC  TG  TT
#  00  01  02  03  10  11  12  13  20  21  22  23  30  31  32  34

# nearest-neighbor energies for Watson-Crick complements at 37C
# (Table 1 in SantaLucia and Hicks 2004)
# ordering of array is
# #                      AA    AC    AG    AT    CA    CC    CG    CT
# _nndGwc = np.array([-1.00,-1.44,-1.28,-0.88,-1.45,-1.84,-2.17,-1.28,
#                     #  GA    GC    GG    GT    TA    TC    TG    TT
#                     -1.30,-2.24,-1.84,-1.44,-0.58,-1.30,-1.45,-1.00],
#                    dtype=np.float32)
#                    # AA   AC   AG   AT   CA   CC   CG   CT
# _nndGwc = np.array([1.00,1.44,1.28,0.88,1.45,1.84,2.17,1.28,
#                    # GA   GC   GG   GT   TA   TC   TG   TT
#                    1.30,2.24,1.84,1.44,0.58,1.30,1.45,1.00],
#                   dtype=np.float32)
# _nndGwcStr = {'AA':1.00,'AC':1.44,'AG':1.28,'AT':0.88,'CA':1.45,'CC':1.84,
#              'CG':2.17,'CT':1.28,'GA':1.30,'GC':2.24,'GG':1.84,'GT':1.44,
#              'TA':0.58,'TC':1.30,'TG':1.45,'TT':1.00}

# nearest-neighbor energies for single mismatches (Table 2 in SantaLucia)
# ordering of array is
#                  # GA/CA GA/CG    AG    AT    CA    CC    CG    CT   GA    GC    GG    GT    TA   TC    TG   TT
# _nndGsmm = np.array([0.17,-1.44,-1.28,-0.88,-1.45,-1.84,-2.17,-1.28,-1.3,-2.24,-1.84,-1.44,-0.58,-1.3,-1.45,-1.0], dtype=np.float32)

_all_pairs = [((i << 2) + j, bits2base[i] + bits2base[j])
              for i in range(4) for j in range(4)]


@lru_cache(maxsize=32)
def calculate_loop_energies_dict(temperature: float, negate: bool = False) -> Dict[str, float]:
    loop_energies = calculate_loop_energies(temperature, negate)
    return {pair[1]: loop_energies[pair[0]] for pair in _all_pairs}


@lru_cache(maxsize=100000)
def wcenergy(seq: str, temperature: float, negate: bool = False) -> float:
    """Return the wc energy of seq binding to its complement."""
    loop_energies = calculate_loop_energies_dict(temperature, negate)
    return sum(loop_energies[seq[i:i + 2]] for i in range(len(seq) - 1))


def wcenergies_str(seqs: Sequence[str], temperature: float, negate: bool = False) -> List[float]:
    seqarr = seqs2arr(seqs)
    return list(calculate_wc_energies(seqarr, temperature, negate))


def wcenergy_str(seq: str, temperature: float, negate: bool = False) -> float:
    seqarr = seqs2arr([seq])
    return list(calculate_wc_energies(seqarr, temperature, negate))[0]


def hash_ndarray(arr: np.ndarray) -> int:
    writeable = arr.flags.writeable
    if writeable:
        arr.flags.writeable = False
    h = hash(bytes(arr.data))  # hash(arr.data)
    arr.flags.writeable = writeable
    return h


CACHE_WC = False
_calculate_wc_energies_cache: Optional[np.ndarray] = None
_calculate_wc_energies_cache_hash: int = 0


def calculate_wc_energies(seqarr: np.ndarray, temperature: float, negate: bool = False) -> np.ndarray:
    """Calculate and store in an array all energies of all sequences in seqarr
    with their Watson-Crick complements."""
    global _calculate_wc_energies_cache
    global _calculate_wc_energies_cache_hash
    if CACHE_WC and _calculate_wc_energies_cache is not None:
        if _calculate_wc_energies_cache_hash == hash_ndarray(seqarr):
            return _calculate_wc_energies_cache
    loop_energies = calculate_loop_energies(temperature, negate)
    left_index_bits = seqarr[:, :-1] << 2
    right_index_bits = seqarr[:, 1:]
    pair_indices = left_index_bits + right_index_bits
    pair_energies = loop_energies[pair_indices]
    energies: np.ndarray = np.sum(pair_energies, axis=1)
    if CACHE_WC:
        _calculate_wc_energies_cache = energies
        _calculate_wc_energies_cache_hash = hash_ndarray(_calculate_wc_energies_cache)
    return energies


def wc_arr(seqarr: np.ndarray) -> np.ndarray:
    """Return numpy array of complements of sequences in `seqarr`."""
    return (3 - seqarr)[:, ::-1]


def prefilter_length_10_11(low_dg: float, high_dg: float, temperature: float, end_gc: bool,
                           convert_to_list: bool = True) \
        -> Union[Tuple[List[str], List[str]], Tuple[DNASeqList, DNASeqList]]:
    """Return sequences of length 10 and 11 with wc energies between given values."""
    s10: DNASeqList = DNASeqList(length=10)
    s11: DNASeqList = DNASeqList(length=11)
    s10 = s10.filter_energy(low=low_dg, high=high_dg, temperature=temperature)
    s11 = s11.filter_energy(low=low_dg, high=high_dg, temperature=temperature)
    forbidden_subs = [f'{a}{b}{c}{d}' for a in ['G', 'C']
                      for b in ['G', 'C']
                      for c in ['G', 'C']
                      for d in ['G', 'C']]
    s10 = s10.filter_substring(forbidden_subs)
    s11 = s11.filter_substring(forbidden_subs)
    if end_gc:
        print(
            'Removing any domains that end in either A or T; '
            'also ensuring every domain has an A or T within 2 indexes of the end')
        s10 = s10.filter_end_gc()
        s11 = s11.filter_end_gc()
    for seqs in (s10, s11):
        if len(seqs) == 0:
            raise ValueError(
                f'low_dg {low_dg:.2f} and high_dg {high_dg:.2f} too strict! '
                f'no sequences of length {seqs.seqlen} found')
    return (s10.to_list(), s11.to_list()) if convert_to_list else (s10, s11)


def all_cats(seq: Sequence[int], seqs: Sequence[int]) -> np.ndarray:
    """
    Return all sequences obtained by concatenating seq to either end of a sequence in seqs.

    For example,

    .. code-block:: Python

        all_cats([0,1,2,3], [[3,3,3], [0,0,0]])

    returns the numpy array

    .. code-block:: Python

        [[0,1,2,3,3,3,3],
         [3,3,3,0,1,2,3],
         [0,1,2,3,0,0,0],
         [0,0,0,0,1,2,3]]
    """
    seqarr = np.asarray([seq])
    seqsarr = np.asarray(seqs)
    ar = seqarr.repeat(seqsarr.shape[0], axis=0)
    ret = np.concatenate((seqsarr, ar), axis=1)
    ret2 = np.concatenate((ar, seqsarr), axis=1)
    ret = np.concatenate((ret, ret2))
    return ret
