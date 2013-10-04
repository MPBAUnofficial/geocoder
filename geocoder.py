import re
import csv
import json

STREET_TYPES = {}


class MatchResult(object):
    """
    match_type can be:
    NO: No match
    A1: perfect match
    A2: unordered perfect match
    A3: perfect match without number
    A4: unordered perfect match without number
    B0: fuzzy match
    match_quality is the level of confidence for a given match.
    it is always 1.0 for levels A1, A2, A3, A4
    """

    def __init__(self, match_type, match_quality):
        #match_type_re = re.compile("^(A[1234]|B0|NO)$")
        #if not match_type_re.search(match_type):
        #    raise ValueError("match_type must be in [A1 A2 A3 A4 B0 NO] got {0}".format(match_type))
        self.match_type = match_type
        self.match_quality = match_quality

    def __cmp__(self, other):
        if self.match_type == "NO":
            if other.match_type == "NO":
                return 0
            else:
                return -1

        if other.match_type == "NO":
            if self.match_type == "NO":
                return 0
            else:
                return 1

        st, sq = self.match_type
        ot, oq = other.match_type
        sq, oq = int(sq), int(oq)

        if st == ot == "A":
            if sq == oq:
                return 0
            elif sq > oq:
                return -1
            else:
                return 1
        elif st == ot == "B":
            if sq == oq:
                if self.match_quality == other.match_quality:
                    return 0
                elif self.match_quality > other.match_quality:
                    return 1
                else:
                    return -1
            elif sq > oq:
                return -1
            else:
                return 1
        else:
            if st == "A" and ot == "B":
                return 1
            else:
                # st == "B" and ot == "A"
                return -1

    def __repr__(self):
        return "{0}: {1}%".format(self.match_type, int(self.match_quality * 100))

    def __str__(self):
        return repr(self)


class QGram(object):
    cache = {}

    def __init__(self, input_strings, q=3):
        self._qgrams = set()
        self._compute_qgrams(input_strings, q)

    def _compute_qgrams(self, input_strings, q):
        for word in input_strings:
            cache_key = word + str(q)
            if cache_key not in self.cache:
                self.cache[cache_key] = self._compute_qgram_word(word, q)

            self._qgrams.update(self.cache[cache_key])

    @staticmethod
    def _compute_qgram_word(word, q):
        # Appends a pattern of p `n` characters long before
        # and after s
        # >>> surround("hello", "#", 2)
        # '##hello##'
        qgrams = set()

        surround = lambda s, p, n: p * n + s + p * n
        surrounded = surround(word, "#", q - 1)
        for i in xrange(len(word) + q - 1):
            qgrams.add(surrounded[i:i + q])

        return qgrams

    def matching_quota(self, other):
        if len(self._qgrams) == 0 or len(other._qgrams) == 0:
            return 0.0

        intersection = float(len(self._qgrams.intersection(other._qgrams)))
        c1 = len(self._qgrams)
        c2 = len(other._qgrams)
        return (intersection / c1 + intersection / c2) / 2


class Address(object):
    split_re = re.compile("[,\s-]+")
    dotted_name_re = re.compile("^(?P<name>[a-zA-Z]+)\.$")
    number_re = re.compile("^(?P<number>\d+)")
    street_types = {}

    @classmethod
    def from_dict(cls, dct, id_column='id', addr_column='address'):
        return cls(dct.get(id_column), dct.get(addr_column))

    def __init__(self, unique_id, address_string):
        self.unique_id = unique_id
        self.original = address_string
        self.tokens = self.split_re.split(address_string.lower().strip())
        self.address_type = None
        self.address_number = None
        self._identify_tokens()

    def _identify_tokens(self):
        #TODO: rework this, global variables are scary beasts
        success, value = self._identify_normalize_address_type(self.tokens[0])
        if success:
            self.address_type = value
            del self.tokens[0]

        if len(self.tokens) == 0:
            return

        number_match = self.number_re.match(self.tokens[-1])
        if number_match:
            address_number = self.tokens.pop(-1)
            number = number_match.group('number')
            self.address_number = str(int(number)) + address_number[len(number):]

    def _identify_normalize_address_type(self, token):
        for street_type, street_type_re in self.street_types.items():
            if street_type_re.search(token):
                return True, street_type

        return False, None

    def _compare_strict(self, other):
        """
        Strict equal only returns no match or a confidence level
        of A1 or A2
        """

        if self.address_type != other.address_type:
            return MatchResult("NO", 0.0)

        if len(self.tokens) != len(other.tokens):
            return MatchResult("NO", 0.0)

        for t1, t2 in zip(self.tokens, other.tokens):
            if t1 != t2:
                return MatchResult("NO", 0.0)

        if self.has_number and self.address_number == other.address_number:
            return MatchResult("A1", 1.0)
        else:
            return MatchResult("A3", 1.0)

    def _match_short_names(self, token_set_one, token_set_two):
        """
        match_short_names takes two sets of tokens, and,
        for each token like `a.` in the first set looks
        for a corresponding long name in set_two.
        It returns a tuple of 4 results.
        The first is a boolean value indicating whether or not
        there was a short token in set_one without corresponding
        long token in set_two.
        The second one is the copy of token_set_one without the
        short tokens that have been matched.
        The third is a copy of token_set_two without the long tokens
        that have been matched to the short ones.
        The fourth and last argument is a dict containing every
        match performed.

        Given the inputs:
        token_set_one = ('a.')
        token_set_two = ('alcide')
        this funcion will return:
        (True, set([]), set([]), {'a.':'alcide'})
        """
        copy_set_one = token_set_one.copy()
        copy_set_two = token_set_two.copy()
        matching_dict = {}


        for token in token_set_one:
            res = self.dotted_name_re.search(token)
            if res:
                initials = res.group('name')
                for other_token in token_set_two:
                    if other_token.startswith(initials):
                        copy_set_one.remove(token)
                        try:
                            copy_set_two.remove(other_token)
                        except KeyError:
                            continue
                        matching_dict[token] = other_token
                        break
                else:
                    return False, None, None, None

        return True, copy_set_one, copy_set_two, matching_dict

    def _compare_unordered(self, other):
        """
        Unordered equal only returns no match or a confidence level of B1 or B2
        """
        self_token_set = set(self.tokens)
        other_token_set = set(other.tokens)

        if len(self_token_set.intersection(other_token_set)) == 0:
            return MatchResult("NO", 0.0)

        if self.address_type != other.address_type:
            return MatchResult("NO", 0.0)

        if len(self_token_set) != len(other_token_set):
            return MatchResult("NO", 0.0)

        self_tokens = self_token_set - other_token_set
        other_tokens = other_token_set - self_token_set

        if len(self_tokens) != len(other_tokens):
            return MatchResult("NO", 0.0)

        if len(self_tokens) == 0 and len(other_tokens) == 0:
            if self.has_number and self.address_number == other.address_number:
                return MatchResult("A2", 1.0)
            else:
                return MatchResult("A4", 1.0)

        result, self_unmatched, other_unmatched, _ = self._match_short_names(self_tokens, other_tokens)

        if not result:
            return MatchResult("NO", 0.0)

        result, other_unmatched, self_unmatched, _ = self._match_short_names(other_unmatched, self_unmatched)

        if not result:
            return MatchResult("NO", 0.0)

        if len(self_unmatched) != 0 or len(other_unmatched) != 0:
            return MatchResult("NO", 0.0)
        else:
            if self.has_number and self.address_number == other.address_number:
                return MatchResult("A2", 1.0)
            else:
                return MatchResult("A4", 1.0)

    def compare_perfect(self, other):
        fc = self._compare_strict(other)
        if fc.match_type == "A1":
            return fc
        oc = self._compare_unordered(other)

        return max(fc, oc)

    def compare_fuzzy(self, other):
        match_type = "B2"
        match_quality = 0.0
        if self.has_type and self.address_type == other.address_type:
            match_quality += 0.10

        if self.has_number and self.address_number == other.address_number:
            match_quality += 0.10
            match_type = "B1"

        sq = QGram(self.tokens)
        oq = QGram(other.tokens)

        mq = sq.matching_quota(oq)
        match_quality += (mq * 0.80)

        return MatchResult(match_type, match_quality)

    def compare(self, other):
        comparisons = [self.compare_perfect, self.compare_fuzzy]
        for comparison in comparisons:
            res = comparison(other)
            if res.match_type != "NO":
                return res

        return res

    @property
    def has_number(self):
        return self.address_number is not None

    @property
    def has_type(self):
        return self.address_type is not None

    def __repr__(self):
        return "{0} {1} {2}".format(self.address_type if self.address_type is not None else "",
                                    " ".join(self.tokens),
                                    self.address_number if self.address_number is not None else "").strip()

    def __str__(self):
        return repr(self)


class Geocoder(object):
    def __init__(self, reference_dataset):
        self.reference_dataset = reference_dataset

    @staticmethod
    def addresses_from_csv(filename, delimiter, id_column, addr_column):
        with open(filename, 'r') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            values = [Address.from_dict(addr, id_column, addr_column) for addr in reader]

        return values

    @classmethod
    def from_csv(cls, filename, delimiter, id_column, addr_column):
        addrs = Geocoder.addresses_from_csv(filename, delimiter, id_column, addr_column)
        if addrs is None:
            return cls([])

        return cls(addrs)

    def localize(self, address_to_localize):
        current_localization, current_comparsion = None, None
        for ref in self.reference_dataset:
            comparsion = address_to_localize.compare(ref)
            if current_comparsion is None:
                current_localization, current_comparsion = ref, comparsion
            else:
                if comparsion > current_comparsion:
                    current_localization, current_comparsion = ref, comparsion

        return current_localization, current_comparsion


def load_street_type(filename):
    with open(filename, 'r') as f:
        data = json.load(f)
    for k, v in data.iteritems():
        Address.street_types[k] = re.compile(v)


def main():
    load_street_type('street_types.json')
    geoc = Geocoder.from_csv('stradario.csv', ',', 'gid', 'fumetto')
    to_localize = Geocoder.addresses_from_csv('indirizzi_con_id.csv', ';', 'id', 'my_indirizzo')

    with open('output.csv', 'w') as f:
        w = csv.writer(f, delimiter=',', quotechar="\"", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["indirizzo_stradario", "id_stradario", "indirizzo_input", "id_input", "livello_confidenza", "percentuale"])
        for i, t in enumerate(to_localize):
            print i + 1
            matching_address, comparison_value = geoc.localize(t)
            w.writerow([str(matching_address),
                        matching_address.unique_id,
                        str(t),
                        t.unique_id,
                        comparison_value.match_type,
                        comparison_value.match_quality])
            f.flush()



if __name__ == '__main__':
    main()