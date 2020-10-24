import numpy as np
import os
from icu import BreakIterator, Locale
import matplotlib.pyplot as plt

from tensorflow import keras
import tensorflow as tf
from keras.models import Sequential
from keras.layers import LSTM
from keras.layers import Dense
from keras.layers import TimeDistributed
from keras.layers import Bidirectional
from keras.layers import Embedding
from keras.layers import Dropout
# from keras import optimizer
from bayes_opt import BayesianOptimization


def is_ascii(input_str):
    """
    A very basic function that checks if all elements of str are ASCII or not
    Args:
        input_str: input string
    """
    return all(ord(char) < 128 for char in input_str)


def diff_strings(str1, str2):
    """
    A function that returns the number of elements of two strings that are not identical
    Args:
        str1: the first string
        str2: the second string
    """
    if len(str1) != len(str2):
        print("Warning: length of two strings are not equal")
    return sum(str1[i] != str2[i] for i in range(len(str1)))


def sigmoid(x):
    """
    Computes the sigmoid function for a scalar
    Args:
        x: the scalar
    """
    return 1.0/(1.0+np.exp(-x))


def print_grapheme_clusters(ratios, thrsh):
    """
    This function analyzes the grapheme clusters, to see what percentage of them form which percent of the text, and
    provides a histogram that shows frequency of grapheme clusters
    ratios: a dictionary that holds the ratio of text that is represented by each grapheme cluster
    Args:
        ratios: a dictionary that shows the percentage of each grapheme cluster
        thrsh: shows what percent of the text we want to cover
    """
    cum_sum = 0
    cnt = 0
    for val in ratios.values():
        cum_sum += val
        cnt += 1
        if cum_sum > thrsh:
            break
    print("number of different grapheme clusters = {}".format(len(ratios.keys())))
    print("{} grapheme clusters form {} of the text".format(cnt, thrsh))
    # plt.hist(ratios.values(), bins=50)
    # plt.show()


def get_segmented_string(str, brkpoints):
    """
    Rerurns a segmented string using the unsegmented string and and break points. Simply inserts | at break points.
    Args:
        str: unsegmented string
        brkpoints: break points
    """
    out = "|"
    for i in range(len(brkpoints)-1):
        out += str[brkpoints[i]: brkpoints[i+1]] + "|"
    return out


def get_bies(char_brkpoints, word_brkpoints):
    """
    Given break points for words and grapheme clusters, returns the matrix that represents BIES.
    The output is a matrix of size (n * 4) where n is the number of grapheme clusters in the string
    Args:
        char_brkpoints: break points for grapheme clusters
        word_brkpoints: break points for words
    """
    bies = np.zeros(shape=[4, len(char_brkpoints)-1])
    word_ind = 0
    for i in range(len(char_brkpoints)-1):
        word_st = word_brkpoints[word_ind]
        word_fn = word_brkpoints[word_ind + 1]
        char_st = char_brkpoints[i]
        char_fn = char_brkpoints[i+1]
        if char_st == word_st and char_fn != word_fn:
            bies[0, i] = 1
            continue
        if char_st != word_st and char_fn != word_fn:
            bies[1, i] = 1
            continue
        if char_st != word_st and char_fn == word_fn:
            bies[2, i] = 1
            word_ind += 1
            continue
        if char_st == word_st and char_fn == word_fn:
            bies[3, i] = 1
            word_ind += 1
            continue
    return bies


def get_bies_string_from_softmax (mat):
    """
    Computes estimated BIES based on a softmax matrix of size n*4.
    Each row of matrix gives four floats that add up to 1, which are probability of B, I, E,  and S.
    This function simply pick the one with highest probability. In ties, it picks B over I, I over E, and E over S.
    Args:
        mat: Input matrix that contains softmax probabilities. Dimension is n*4 where n is length of the string.
    """
    out = ""
    for i in range(mat.shape[0]):
        max_softmax = max(mat[i, :])
        if mat[i, 0] == max_softmax:
            out += "b"
        elif mat[i, 1] == max_softmax:
            out += "i"
        elif mat[i, 2] == max_softmax:
            out += "e"
        elif mat[i, 3] == max_softmax:
            out += "s"
    return out


def remove_tags(line, st_tag, fn_tag):
    """
    Given a string and two substrings, remove any text between these tags.
    It handles spaces around tags as follows:
        abc|<NE>def</NE>|ghi      ---> abc|ghi
        abc| |<NE>def</NE>|ghi    ---> abc| |ghi
        abc|<NE>def</NE>| |ghi    ---> abc| |ghi
        abc| |<NE>def</NE>| |ghi  ---> abc| |ghi
    Args:
        line: the input string
        st_tag: the first substring
        fn_tag: the secibd substring
    """

    new_line = ""
    st_ind = 0
    while st_ind < len(line):
        if line[st_ind: st_ind+len(st_tag)] == st_tag:
            fn_ind = st_ind
            while fn_ind < len(line):
                if line[fn_ind: fn_ind+len(fn_tag)] == fn_tag:
                    fn_ind = fn_ind+len(fn_tag) + 1
                    if st_ind -2 >= 0 and fn_ind+2 <= len(line):
                        if line[st_ind-2:st_ind] == " |" and line[fn_ind:fn_ind+2] == " |":
                            fn_ind += 2
                    st_ind = fn_ind
                    break
                else:
                    fn_ind += 1
        if st_ind < len(line):
            new_line += line[st_ind]
        st_ind += 1
    return new_line


def clean_line(line):
    """
    This line cleans a line as follows such that it is ready for process by different components of the code. It returns
    the clean line or -1, if the line should be omitted.
        1) remove tags and https from the line.
        2) Put a | at the begining and end of the line if it isn't already there
        3) if line is very short (len < 3) or if it is all in English or it has a link in it, return -1
    Args:
        line: the input line
    """
    line = line.strip()

    # Remove lines with links
    if "http" in line or len(line) == 0:
        return -1

    # Remove texts between following tags
    line = remove_tags(line, "<NE>", "</NE>")
    line = remove_tags(line, "<AB>", "</AB>")

    # Remove lines that are all fully in English
    if is_ascii(line):
        return -1

    # Add "|" to the end of each line if it is not there
    if len(line) >= 1 and line[len(line) - 1] != '|':
        line += "|"

    # Adding "|" to the start of each line if it is not there
    if line[0] != '|':
        line = '|' + line

    return line


def preprocess_Thai(demonstrate):
    """
    This function uses the BEST data set to
        1) compute the grapheme cluster dictionary that holds the frequency of different grapheme clusters
        2) demonstrate the performance of icu word breakIterator and compute its accuracy
    Args:
        demonstrate: shows if we want to see how the algorithm is working or not
    """
    words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
    chars_break_iterator = BreakIterator.createCharacterInstance(Locale.getUS())
    grapheme_clusters_dic = dict()
    icu_mismatch = 0
    icu_total_bies_lengths = 0
    for cat in ["news", "encyclopedia", "article", "novel"]:
        for text_num in range(1, 96):
            text_num_str = "{}".format(text_num).zfill(5)
            # file = open("./Data/Best/{}/{}_".format(cat, cat) + text_num_str + ".txt", 'r')
            file = "./Data/Best/{}/{}_".format(cat, cat) + text_num_str + ".txt"
            line_counter = 0
            with open(file) as f:
                for line in f:
                    line_counter += 1
                    line = clean_line(line)
                    if line == -1:
                        continue
                    # Finding word breakpoints using the segmented data
                    word_brkpoints = []
                    found_bars = 0
                    for i in range(len(line)):
                        if line[i] == '|':
                            word_brkpoints.append(i - found_bars)
                            found_bars += 1

                    # Creating the unsegmented line
                    unsegmented_line = line.replace("|", "")

                    # Making the grapheme clusters brkpoints
                    chars_break_iterator.setText(unsegmented_line)
                    char_brkpoints = [0]
                    for brkpoint in chars_break_iterator:
                        char_brkpoints.append(brkpoint)

                    # Storing the grapheme clusters and their frequency in the dictionary
                    for i in range(len(char_brkpoints) - 1):
                        grapheme_clusters_dic[
                            unsegmented_line[char_brkpoints[i]: char_brkpoints[i + 1]]] = grapheme_clusters_dic.get(
                            unsegmented_line[char_brkpoints[i]: char_brkpoints[i + 1]], 0) + 1
                    true_bies = get_bies(char_brkpoints, word_brkpoints)
                    true_bies_str = get_bies_string_from_softmax(np.transpose(true_bies))

                    # Compute segmentations of icu and BIES associated with it
                    words_break_iterator.setText(unsegmented_line)
                    icu_word_brkpoints = [0]
                    for brkpoint in words_break_iterator:
                        icu_word_brkpoints.append(brkpoint)
                    icu_word_segmented_str = get_segmented_string(unsegmented_line, icu_word_brkpoints)
                    icu_bies = get_bies(char_brkpoints, icu_word_brkpoints)
                    icu_bies_str = get_bies_string_from_softmax(np.transpose(icu_bies))

                    # Counting the number of mismatches between icu_bies and true_bies
                    icu_total_bies_lengths += len(icu_bies_str)
                    icu_mismatch += diff_strings(true_bies_str, icu_bies_str)

                    # Demonstrate how icu segmenter works
                    if demonstrate:
                        char_segmented_str = get_segmented_string(unsegmented_line, char_brkpoints)
                        print("Cat: {}, Text number: {}".format(cat, text_num))
                        print("LINE {} - UNSEG LINE       : {}".format(line_counter, unsegmented_line))
                        print("LINE {} - TRUE SEG LINE    : {}".format(line_counter, line))
                        print("LINE {} - ICU SEG LINE     : {}".format(line_counter, icu_word_segmented_str))
                        print("LINE {} - GRAPHEME CLUSTERS: {}".format(line_counter, char_segmented_str))
                        print("LINE {} - TRUE BIES STRING : {}".format(line_counter, true_bies_str))
                        print("LINE {} -  ICU BIES STRING : {}".format(line_counter, icu_bies_str))
                        print("LINE {} - TRUE WORD BREAKS : {}".format(line_counter, word_brkpoints))
                        print('**********************************************************************************')

                    line_counter += 1

    icu_accuracy = 1 - icu_mismatch/icu_total_bies_lengths
    graph_clust_freq = grapheme_clusters_dic
    graph_clust_freq = {k: v for k, v in sorted(graph_clust_freq.items(), key=lambda item: item[1], reverse=True)}
    graph_clust_ratio = graph_clust_freq
    total = sum(graph_clust_ratio.values(), 0.0)
    graph_clust_ratio = {k: v / total for k, v in graph_clust_ratio.items()}

    return graph_clust_ratio, icu_accuracy


def preprocess_Burmese(demonstrate):
    """
    This function uses the Okell data set to
        1) Clean it by removing tabs from start of it
        1) Compute the grapheme cluster dictionary that holds the frequency of different grapheme clusters
        2) Demonstrate the performance of icu word breakIterator and compute its accuracy
    """
    words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
    chars_break_iterator = BreakIterator.createCharacterInstance(Locale.getUS())
    grapheme_clusters_dic = dict()
    file = "./Data/my.txt"
    with open(file) as f:
        line_counter = 0
        for line in f:
            line = line.strip()
            # If the resulting line is in ascii (including an empty line) continue
            if is_ascii(line):
                continue
            # Making the grapheme clusters brkpoints
            chars_break_iterator.setText(line)
            char_brkpoints = [0]
            for brkpoint in chars_break_iterator:
                char_brkpoints.append(brkpoint)

            # Storing the grapheme clusters and their frequency in the dictionary
            for i in range(len(char_brkpoints) - 1):
                grapheme_clusters_dic[
                    line[char_brkpoints[i]: char_brkpoints[i + 1]]] = grapheme_clusters_dic.get(
                    line[char_brkpoints[i]: char_brkpoints[i + 1]], 0) + 1

            # Compute segmentations of icu and BIES associated with it
            words_break_iterator.setText(line)
            icu_word_brkpoints = [0]
            for brkpoint in words_break_iterator:
                icu_word_brkpoints.append(brkpoint)
            icu_word_segmented_str = get_segmented_string(line, icu_word_brkpoints)
            icu_bies = get_bies(char_brkpoints, icu_word_brkpoints)
            icu_bies_str = get_bies_string_from_softmax(np.transpose(icu_bies))

            # Demonstrate how icu segmenter works
            if demonstrate:
                char_segmented_str = get_segmented_string(line, char_brkpoints)
                print("LINE {} - UNSEG LINE       : {}".format(line_counter, line))
                print("LINE {} - ICU SEG LINE     : {}".format(line_counter, icu_word_segmented_str))
                print("LINE {} - GRAPHEME CLUSTERS: {}".format(line_counter, char_segmented_str))
                print("LINE {} -  ICU BIES STRING : {}".format(line_counter, icu_bies_str))
                print('**********************************************************************************')
            line_counter += 1
    graph_clust_freq = grapheme_clusters_dic
    graph_clust_freq = {k: v for k, v in sorted(graph_clust_freq.items(), key=lambda item: item[1], reverse=True)}
    graph_clust_ratio = graph_clust_freq
    total = sum(graph_clust_ratio.values(), 0.0)
    graph_clust_ratio = {k: v / total for k, v in graph_clust_ratio.items()}
    return graph_clust_ratio


def add_additional_bars(read_filename, write_filename):
    """
    This function reads a segmented file and add bars around each space in it. It assumes that spaces are used as
    breakpoints in the segmentation (just like "|")
    Args:
        read_filename: Address of the input file
        write_filename: Address of the output file
    """
    wfile = open(write_filename, 'w')
    with open(read_filename) as f:
        for line in f:
            line = line.strip()
            if len(line) == 0:
                continue
            new_line = ""
            for i in range(len(line)):
                ch = line[i]
                if ch == " ":
                # If you want to put lines bars around punctuations as well, you should use comment previous if and
                # uncomment the next if.
                # The following if will put bars for !? as |!||?| instead of |!|?|. This should be fixed if the
                # following if is going to be used. It can easily be fixed by keeping track of the last character in
                # new_line.
                # if 32 <= ord(ch) <= 47 or 58 <= ord(ch) <= 64:
                    if i == 0:
                        if i+1 < len(line) and line[i+1] == "|":
                            new_line = new_line + "|" + ch
                        else:
                            new_line = new_line + "|" + ch + "|"
                    elif i == len(line)-1:
                        if line[i-1] == "|":
                            new_line = new_line + ch + "|"
                        else:
                            new_line = new_line + "|" + ch + "|"
                    else:
                        if line[i-1] != "|" and line[i+1] != "|":
                            new_line = new_line + "|" + ch + "|"
                        if line[i-1] == "|" and line[i+1] != "|":
                            new_line = new_line + ch + "|"
                        if line[i-1] != "|" and line[i+1] == "|":
                            new_line = new_line + "|" + ch
                        if line[i-1] == "|" and line[i+1] == "|":
                            new_line = new_line + ch
                else:
                    new_line += ch
            new_line += "\n"
            wfile.write(new_line)


def compute_ICU_accuracy(filename):
    """
    This function uses a dataset to compute the accuracy of icu word breakIterator
    Args:
        filename: The path of the file
    """
    chars_break_iterator = BreakIterator.createCharacterInstance(Locale.getUS())
    line_counter = 0
    icu_mismatch = 0
    icu_total_bies_lengths = 0
    with open(filename) as f:
        for line in f:
            line = clean_line(line)
            if line == -1:
                continue

            # Finding word breakpoints using the segmented data
            word_brkpoints = []
            found_bars = 0
            for i in range(len(line)):
                if line[i] == '|':
                    word_brkpoints.append(i - found_bars)
                    found_bars += 1

            # Creating the unsegmented line
            unsegmented_line = line.replace("|", "")

            # Making the grapheme clusters brkpoints
            chars_break_iterator.setText(unsegmented_line)
            char_brkpoints = [0]
            for brkpoint in chars_break_iterator:
                char_brkpoints.append(brkpoint)
            true_bies = get_bies(char_brkpoints, word_brkpoints)
            true_bies_str = get_bies_string_from_softmax(np.transpose(true_bies))

            # Compute segmentations of icu and BIES associated with it
            words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
            words_break_iterator.setText(unsegmented_line)
            icu_word_brkpoints = [0]
            for brkpoint in words_break_iterator:
                icu_word_brkpoints.append(brkpoint)
            icu_bies = get_bies(char_brkpoints, icu_word_brkpoints)
            icu_bies_str = get_bies_string_from_softmax(np.transpose(icu_bies))

            # Counting the number of mismatches between icu_bies and true_bies
            icu_total_bies_lengths += len(icu_bies_str)
            icu_mismatch += diff_strings(true_bies_str, icu_bies_str)

            line_counter += 1
        icu_accuracy = 1 - icu_mismatch / icu_total_bies_lengths
        return icu_accuracy


def divide_train_test_data(input_text, train_text, valid_text, test_text):
    """
    This function divides a file into three new files, that contain train data, validation data, and testing data
    Args:
        input_text: address of the original file
        train_text: address to store the train data in it
        valid_text: address to store the validation data in it
        test_text: address to store the test file in it
    """
    train_ratio = 0.4
    valid_ratio = 0.4
    train_file = open(train_text, 'w')
    valid_file = open(valid_text, 'w')
    test_file = open(test_text, 'w')
    num_lines = sum(1 for _line in open(input_text))
    line_counter = 0
    with open(input_text) as f:
        for line in f:
            line_counter += 1
            line = line.strip()
            if is_ascii(line):
                continue
            if line_counter <= num_lines*train_ratio:
                train_file.write(line + "\n")
            elif num_lines*train_ratio < line_counter <= num_lines*(train_ratio+valid_ratio):
                valid_file.write(line + "\n")
            else:
                test_file.write(line + "\n")


def get_BEST_text(starting_text, ending_text, pseudo):
    """
    Gives a long string, that contains all lines (separated by a single space) from BEST data with numbers in a range
    This function uses data from all sources (news, encyclopedia, article, and novel)
    It removes all texts between pair of tags (<NE>, </NE>) and (<AB>, </AB>), assures that the string ends with a "|",
    and ignores empty lines, lines with "http" in them, and lines that are all in english (since these are not segmented
    in the BEST data set)
    Args:
        starting_text: number or the smallest text
        ending_text: number or the largest text + 1
        pseudo: if True, it means we use pseudo segmented data, if False, we use BEST segmentation
    """
    words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
    category = ["news", "encyclopedia", "article", "novel"]
    out_str = ""
    for text_num in range(starting_text, ending_text):
        for cat in category:
            text_num_str = "{}".format(text_num).zfill(5)
            file = "./Data/Best/{}/{}_".format(cat, cat) + text_num_str + ".txt"
            with open(file) as f:
                for line in f:
                    line = clean_line(line)
                    if line == -1:
                        continue
                    # If pseudo is True then unsegment the text and re-segment it using ICU
                    if pseudo:
                        unsegmented_line = line.replace("|", "")
                        words_break_iterator.setText(unsegmented_line)
                        icu_word_brkpoints = [0]
                        for brkpoint in words_break_iterator:
                            icu_word_brkpoints.append(brkpoint)
                        line = get_segmented_string(unsegmented_line, icu_word_brkpoints)
                    if len(out_str) == 0:
                        out_str = line
                    else:
                        out_str = out_str + " " + line
    return out_str


def get_burmese_text(filename):
    """
    This function first combine all lines in a file where each two lines are separated with a space, and then uses ICU
    to segment the new long string.
    Note: Because in some of the Burmese texts some lines start with glyphs that are not valid, I first combine all
    lines and then segment them, rather than first segmenting each line and then combining them. This can result in a
    more robust segmentation. Eample: see line 457457 of the my_train.txt
    of the
    Args:
        filename: address of the input file
    """
    words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
    out_str = ""
    line_counter = 0
    with open(filename) as f:
        for line in f:
            line_counter += 1
            line = line.strip()
            if is_ascii(line):
                continue
            if len(out_str) == 0:
                out_str = line
            else:
                out_str = out_str + " " + line

    words_break_iterator.setText(out_str)
    icu_word_brkpoints = [0]
    for brkpoint in words_break_iterator:
        icu_word_brkpoints.append(brkpoint)
    out_str = get_segmented_string(out_str, icu_word_brkpoints)
    return out_str


def get_file_text(filename):
    """
    Gives a long string, that contains all lines (separated by a single space) from a file.
    It removes all texts between pair of tags (<NE>, </NE>) and (<AB>, </AB>), assures that each line starts and ends
    with a "|", and ignores empty lines, lines with "http" in them, and lines that are all in english (since these are
    usually not segmented)
    Args:
        filename: address of the file
    """
    line_counter = 0
    out_str = ""
    with open(filename) as f:
        for line in f:
            line = clean_line(line)
            if line == -1:
                continue
            if len(out_str) == 0:
                out_str = line
            else:
                out_str = out_str + " " + line
            line_counter += 1
    return out_str


def get_trainable_data(input_line, graph_clust_ids):
    """
    Given a segmented line, extracts x_data (with respect to a dictionary that maps grapheme clusters to integers)
    and y_data which is a n*4 matrix that represents BIES where n is the length of the unsegmented line. All grapheme
    clusters not found in the dictionary are set to the largest value of the dictionary plus 1
    Args:
        input_line: the unsegmented line
        graph_clust_ids: a dictionary that stores maps from grapheme clusters to integers
    """
    # Finding word breakpoints
    word_brkpoints = []
    found_bars = 0
    for i in range(len(input_line)):
        if input_line[i] == '|':
            word_brkpoints.append(i - found_bars)
            found_bars += 1
    unsegmented_line = input_line.replace("|", "")

    # Finding grapheme cluster breakpoints
    chars_break_iterator = BreakIterator.createCharacterInstance(Locale.getUS())
    chars_break_iterator.setText(unsegmented_line)
    char_brkpoints = [0]
    for brkpoint in chars_break_iterator:
        char_brkpoints.append(brkpoint)

    # Finding BIES
    true_bies = get_bies(char_brkpoints, word_brkpoints)

    # Making x_data and y_data
    times = len(char_brkpoints)-1
    x_data = np.zeros(shape=[times, 1])
    y_data = np.zeros(shape=[times, 4])
    excess_grapheme_ids = max(graph_clust_ids.values()) + 1
    for i in range(times):
        char_st = char_brkpoints[i]
        char_fn = char_brkpoints[i + 1]
        curr_char = unsegmented_line[char_st: char_fn]
        x_data[i, 0] = graph_clust_ids.get(curr_char, excess_grapheme_ids)
        y_data[i, :] = true_bies[:, i]
    return x_data, y_data


def compute_hc(weight, x_t, h_tm1, c_tm1):
    """
    Given weights of a LSTM model, the input at time t, and values for h and c at time t-1, compute the values of h and
    c for time t.
    Args:
        weights: a list of three matrices, which are W (from input to cell), U (from h to cell), and b (bias) respectively.
        Dimensions: warr.shape = (embedding_dim, hunits*4), uarr.shape = (hunits, hunits*4), barr.shape = (hunits*4,)
    """
    warr, uarr, barr = weight
    warr = warr.numpy()
    uarr = uarr.numpy()
    barr = barr.numpy()

    # Implementing gates (forget, input, and output)
    s_t = (x_t.dot(warr) + h_tm1.dot(uarr) + barr)
    hunit = uarr.shape[0]
    i = sigmoid(s_t[:, :hunit])
    f = sigmoid(s_t[:, 1 * hunit:2 * hunit])
    _c = np.tanh(s_t[:, 2 * hunit:3 * hunit])
    o = sigmoid(s_t[:, 3 * hunit:])
    c_t = i * _c + f * c_tm1
    h_t = o * np.tanh(c_t)
    return [h_t, c_t]


def LSTM_score(hunits, embedding_dim):
    """
    Given the number of LSTM cells and embedding dimension, this function computes a score for a bi-directional LSTM
    model which is basically the accuracy of the model minus a weighted penalty function linear in number of parameters
    Args:
        hunits: number of LSTM cells in bi-directional LSTM model
        embedding_dim: length of output of the embedding layer
    """
    hunits = int(round(hunits))
    embedding_dim = int(round(embedding_dim))
    word_segmenter = WordSegmenter(input_n=50, input_t=100000, input_graph_clust_dic=graph_clust_dic,
                                   input_embedding_dim=embedding_dim, input_hunits=hunits, input_dropout_rate=0.2,
                                   input_output_dim=4, input_epochs=3, input_training_data="BEST",
                                   input_evaluating_data="BEST")
    word_segmenter.train_model()
    fitted_model = word_segmenter.get_model()
    lam = 1/88964  # This is number of parameters in the largest model
    C = 0
    return word_segmenter.test_model() - C * lam * fitted_model.count_params()


def store_ICU_segmented_file(unseg_filename, seg_filename):
    """
    This function uses ICU to segment a file line by line and store that segmented file
    Args:
        unseg_filename: address of the unsegmented file
        seg_filename: address that the segmented file will be stored
    """
    words_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
    wfile = open(seg_filename, 'w')
    with open(unseg_filename) as f:
        for line in f:
            line = line.strip()
            if len(line) == 0:
                continue
            words_break_iterator.setText(line)
            icu_word_brkpoints = [0]
            for brkpoint in words_break_iterator:
                icu_word_brkpoints.append(brkpoint)
            segmented_line = get_segmented_string(line, icu_word_brkpoints)
            wfile.write(segmented_line + "\n")


def perfom_bayesian_optimization(hunits_lower, hunits_upper, embedding_dim_lower, embedding_dim_upper):
    """
    This function implements Bayesian optimization to search in a range of possible values for number of LSTM cells and
    embedding dimension to find the most accurate and parsimonious model. It uses the function LSTM_score to compute
    score of each model.
    Args:
        hunits_lower and hunits_upper: lower and upper bound of search region for number of LSTM cells
        embedding_dim_lower and embedding_dim_upper: lower and upper bound of search region for embedding dimension
    """
    bounds = {'hunits': (hunits_lower, hunits_upper), 'embedding_dim': (embedding_dim_lower, embedding_dim_upper)}
    optimizer = BayesianOptimization(
        f=LSTM_score,
        pbounds=bounds,
        random_state=1,
    )
    optimizer.maximize(init_points=2, n_iter=10)
    print(optimizer.max)
    print(optimizer.res)


class KerasBatchGenerator(object):
    """
    A batch generator component, which is used to generate batches for training, validation, and evaluation. The current
    version works only for inputs of dimension 1.
    Args:
        x_data: The input of the model
        y_data: The output of the model
        n: length of the input and output in each batch
        batch_size: number of batches
        dim_output: dimension of the output
    """
    def __init__(self, x_data, y_data, n, batch_size, dim_output):
        self.x_data = x_data  # dim = times * dim_features
        self.y_data = y_data  # dim = times * dim_output
        self.n = n
        self.batch_size = batch_size
        self.dim_output = dim_output
        if x_data.shape[0] < batch_size * n or y_data.shape[0] < batch_size * n:
            print("Warning: x_data or y_data is not large enough!")

    def generate(self):
        """
        generates batches one by one, used for training and validation
        """
        x = np.zeros([self.batch_size, self.n])
        y = np.zeros([self.batch_size, self.n, self.dim_output])
        while True:
            for i in range(self.batch_size):
                x[i, :] = self.x_data[self.n * i: self.n * (i + 1), 0]
                y[i, :, :] = self.y_data[self.n * i: self.n * (i + 1), :]
            yield x, y

    def generate_all_batches(self):
        """
        returns all batches together, used mostly for testing
        """
        x = np.zeros([self.batch_size, self.n])
        y = np.zeros([self.batch_size, self.n, self.dim_output])
        for i in range(self.batch_size):
            x[i, :] = self.x_data[self.n * i: self.n * (i + 1), 0]
            y[i, :, :] = self.y_data[self.n * i: self.n * (i + 1), :]
        return x, y


class WordSegmenter:
    """
    A class that let you make a bi-directional LSTM, train it, and test it. It assumes that the number of features is 1.
    Args:
        input_n: Length of the input for LSTM model
        input_t: The total length of data used to train and validate the model. It is equal to number of batches times n
        input_graph_clust_dic: a dictionary that maps the most frequent grapheme clusters to integers
        input_embedding_dim: length of the embedding vectors for each grapheme cluster
        input_hunits: number of units used in each cell of LSTM
        input_dropout_rate: dropout rate used in layers after the embedding and after the bidirectional LSTM
        input_output_dim: dimension of the output layer
        input_epochs: number of epochs used to train the model
        input_training_data: name of the data used to train the model
        input_evaluating_data: name of the data used to evaluate the model
    """
    def __init__(self, input_n, input_t, input_graph_clust_dic, input_embedding_dim, input_hunits, input_dropout_rate,
                 input_output_dim, input_epochs, input_training_data, input_evaluating_data):
        self.n = input_n
        self.t = input_t
        if self.t % self.n != 0:
            print("Warning: t is not divided by n")
        self.batch_size = self.t // self.n  # number of batches used to train the model. It is defined as t // n
        self.graph_clust_dic = input_graph_clust_dic
        self.clusters_num = len(self.graph_clust_dic.keys()) + 1  # number of grapheme clusters in graph_clust_dic
        self.embedding_dim = input_embedding_dim
        self.hunits = input_hunits
        self.dropout_rate = input_dropout_rate
        self.output_dim = input_output_dim
        self.epochs = input_epochs
        self.training_data = input_training_data
        self.evaluating_data = input_evaluating_data
        self.model = None

    def train_model(self):
        """
        This function trains the model using the dataset specified in the __init__ function. It combine all sentences in
        the data set with a space between them and then divide this large string into strings of fixed length self.n.
        Therefore, it may (and probably will) break some words and puts different part of them in different batches.
        """

        # Get training data of length self.t
        x_data = []
        y_data = []
        if self.training_data == "BEST":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_BEST_text(starting_text=1, ending_text=10, pseudo=False)
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the training data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]

        elif self.training_data == "pseudo BEST":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_BEST_text(starting_text=1, ending_text=10, pseudo=True)
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the training data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]

        elif self.training_data == "my":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_burmese_text("./Data/my_train.txt")
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the training data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]
        else:
            print("Warning: no implementation for this training data exists!")
        train_generator = KerasBatchGenerator(x_data, y_data, n=self.n, batch_size=self.batch_size,
                                              dim_output=self.output_dim)

        # Get validation data of length self.t
        if self.training_data == "BEST":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_BEST_text(starting_text=10, ending_text=20, pseudo=False)
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the validation data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]
        elif self.training_data == "pseudo BEST":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_BEST_text(starting_text=10, ending_text=20, pseudo=True)
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the validation data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]
        elif self.training_data == "my":
            # this chunk of data has ~ 2*10^6 data points
            input_str = get_burmese_text("./Data/my_valid.txt")
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
            if self.t > x_data.shape[0]:
                print("Warning: size of the training data is less than self.t")
            x_data = x_data[:self.t]
            y_data = y_data[:self.t, :]
        else:
            print("Warning: no implementation for this validation data exists!")
        valid_generator = KerasBatchGenerator(x_data, y_data, n=self.n, batch_size=self.batch_size,
                                              dim_output=self.output_dim)

        # Building the model
        model = Sequential()
        model.add(Embedding(self.clusters_num, self.embedding_dim, input_length=self.n))
        model.add(Dropout(self.dropout_rate))
        model.add(Bidirectional(LSTM(self.hunits, return_sequences=True), input_shape=(self.n, 1)))
        model.add(Dropout(self.dropout_rate))
        model.add(TimeDistributed(Dense(self.output_dim, activation='softmax')))
        opt = keras.optimizers.Adam(learning_rate=0.1)
        # opt = keras.optimizers.SGD(learning_rate=0.4, momentum=0.9)
        model.compile(loss='categorical_crossentropy', optimizer=opt, metrics=['accuracy'])

        # Fitting the model
        model.fit(train_generator.generate(), steps_per_epoch=self.t//self.batch_size,
                  epochs=self.epochs, validation_data=valid_generator.generate(),
                  validation_steps=self.t//self.batch_size)
        self.model = model

    def test_model(self):
        """
        This function tests the model fitted in self.train(). It uses the same format (combining all sentences separated
         by spaces) to test the model.
        """
        # Get test data
        x_data = []
        y_data = []
        if self.evaluating_data == "BEST":
            input_str = get_BEST_text(starting_text=40, ending_text=45, pseudo=False)
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
        elif self.evaluating_data == "SAFT":
            input_str = get_file_text("./Data/SAFT/test.txt")
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
        elif self.evaluating_data == "my":
            input_str = get_burmese_text("./Data/my_test.txt")
            x_data, y_data = get_trainable_data(input_str, self.graph_clust_dic)
        else:
            print("Warning: no implementation for this evaluation data exists!")
        test_batch_size = x_data.shape[0]//self.n
        test_generator = KerasBatchGenerator(x_data, y_data, n=self.n, batch_size=test_batch_size,
                                             dim_output=self.output_dim)

        # Testing batch by batch (each batch of length self.n)
        all_test_input, all_actual_y = test_generator.generate_all_batches()
        all_y_hat = self.model.predict(all_test_input)
        test_acc = []
        for i in range(test_batch_size):
            actual_y = all_actual_y[i, :, :]
            actual_y = get_bies_string_from_softmax(actual_y)
            y_hat = all_y_hat[i, :, :]
            y_hat = get_bies_string_from_softmax(y_hat)

            # Compute the BIES accuracy
            mismatch = diff_strings(actual_y, y_hat)
            test_acc.append(1 - mismatch / len(actual_y))
        test_acc = np.array(test_acc)
        print("the average test accuracy in test_model function: {}".format(np.mean(test_acc)))
        return np.mean(test_acc)

    def test_text_line_by_line(self, file, line_limit):
        """
        This function tests the model fitted in self.train() using BEST data set. Unlike test_model() function, this
        function tests the model line by line. It combines very short lines together before testing.
        Args:
            file: the address of the file that is going to be tested
            line_limit: number of lines to be tested
        """
        test_acc = []
        prev_str = ""
        line_counter = 0
        with open(file) as f:
            for line in f:
                if line_counter == line_limit:
                    break
                line = clean_line(line)
                if line == -1:
                    continue
                line_counter += 1
                # If the new line is too short, combine it with previous short lines. Process it if it gets long enough.
                # If this value is set to infinity, basically we are converting the whole text into one big string and
                # evaluating that; just like test_model() function
                if len(line) < 30:
                    prev_str = prev_str + line
                    if len(prev_str) >= 50:
                        line = prev_str
                        prev_str = ""
                    else:
                        continue
                # Get trainable data
                x_data, y_data = get_trainable_data(line, self.graph_clust_dic)

                # Use the manual predict function -- tf function doesn't always work properly for varying length strings
                y_hat = self.manual_predict(x_data)
                y_hat = get_bies_string_from_softmax(y_hat)
                actual_y = get_bies_string_from_softmax(y_data)

                # Compute the BIES accuracy
                mismatch = diff_strings(actual_y, y_hat)
                test_acc.append(1 - mismatch / len(actual_y))
            print("the average test accuracy (line by line) for file {} : {}".format(file, np.mean(test_acc)))
            return test_acc

    def test_model_line_by_line(self):
        """
        This function uses the test_text_line_by_line() to test the model by a range of texts in BEST data set. The
        final score is the average of scores computed for each individual text.
        """
        all_test_acc = []
        if self.evaluating_data == "BEST":
            category = ["news", "encyclopedia", "article", "novel"]
            for text_num in range(40, 45):
                print("testing text {}".format(text_num))
                for cat in category:
                    text_num_str = "{}".format(text_num).zfill(5)
                    file = "./Data/Best/{}/{}_".format(cat, cat) + text_num_str + ".txt"
                    all_test_acc += self.test_text_line_by_line(file, line_limit=-1)
        elif self.evaluating_data == "my":
            file = "./Data/my_test_segmented.txt"
            num_lines = sum(1 for _line in open(file))
            line_limit = 2000
            if line_limit > num_lines:
                print("Warning: number of lines you are using is larger than the total numbe of lines in " + file)
            all_test_acc += self.test_text_line_by_line(file, line_limit=line_limit)
        else:
            print("Warning: no implementation for this evaluation data exists!")
        print("the average test accuracy by test_model_line_by_line function: {}".format(np.mean(all_test_acc)))

        return np.mean(all_test_acc)

    def manual_predict(self, test_input):
        """
        Implementation of the tf.predict function manually. This function works for inputs of any length, and only uses
        model weights obtained from self.model.weights.
        Args:
            test_input: the input text
        """
        # Forward LSTM
        embedarr = self.model.weights[0]
        embedarr = embedarr.numpy()
        weightLSTM = self.model.weights[1: 4]
        c_fw = np.zeros([1, self.hunits])
        h_fw = np.zeros([1, self.hunits])
        all_h_fw = np.zeros([len(test_input), self.hunits])
        for i in range(len(test_input)):
            input_graph_id = int(test_input[i])
            x_t = embedarr[input_graph_id, :]
            x_t = x_t.reshape(1, x_t.shape[0])
            h_fw, c_fw = compute_hc(weightLSTM, x_t, h_fw, c_fw)
            all_h_fw[i, :] = h_fw

        # Backward LSTM
        embedarr = self.model.weights[0]
        embedarr = embedarr.numpy()
        weightLSTM = self.model.weights[4: 7]
        c_bw = np.zeros([1, self.hunits])
        h_bw = np.zeros([1, self.hunits])
        all_h_bw = np.zeros([len(test_input), self.hunits])
        for i in range(len(test_input) - 1, -1, -1):
            input_graph_id = int(test_input[i])
            x_t = embedarr[input_graph_id, :]
            x_t = x_t.reshape(1, x_t.shape[0])
            h_bw, c_bw = compute_hc(weightLSTM, x_t, h_bw, c_bw)
            all_h_bw[i, :] = h_bw

        # Combining Forward and Backward layers through dense time-distributed layer
        timew = self.model.weights[7]
        timew = timew.numpy()
        timeb = self.model.weights[8]
        timeb = timeb.numpy()
        est = np.zeros([len(test_input), 4])
        for i in range(len(test_input)):
            final_h = np.concatenate((all_h_fw[i, :], all_h_bw[i, :]), axis=0)
            final_h = final_h.reshape(1, 2 * self.hunits)
            curr_est = final_h.dot(timew) + timeb
            curr_est = curr_est[0]
            curr_est = np.exp(curr_est) / sum(np.exp(curr_est))
            est[i, :] = curr_est
        return est

    def get_model(self):
        return self.model

    def set_model(self, input_model):
        self.model = input_model

################################ Thai ################################

# Adding space bars to the SAFT data around spaces
# add_additional_bars("./Data/SAFT/test_raw.txt", "./Data/SAFT/test.txt")

# Looking at the accuracy of the ICU on SAFT data set
# print("Accuracy of ICU on SAFT data is {}.".format(compute_ICU_accuracy(os.getcwd() + "/Data/SAFT/test.txt")))

# Preprocess the Thai language
# Thai_graph_clust_ratio, icu_accuracy = preprocess_Thai(demonstrate=False)
# print("icu accuracy on BEST data is {}".format(icu_accuracy))
# np.save(os.getcwd() + '/Data/Thai_graph_clust_ratio.npy', Thai_graph_clust_ratio)

# Loading the graph_clust from memory
graph_clust_ratio = np.load(os.getcwd() + '/Data/Thai_graph_clust_ratio.npy', allow_pickle=True).item()
# print(graph_clust_ratio)
# print_grapheme_clusters(ratios=graph_clust_ratio, thrsh=0.999)

# Performing Bayesian optimization to find the best value for hunits and embedding_dim
'''
cnt = 0
graph_thrsh = 350  # The vocabulary size for embeddings
graph_clust_dic = dict()
for key in graph_clust_ratio.keys():
    if cnt < graph_thrsh-1:
        graph_clust_dic[key] = cnt
    if cnt == graph_thrsh-1:
        break
    cnt += 1
perfom_bayesian_optimization(hunits_lower=4, hunits_upper=64, embedding_dim_lower=4, embedding_dim_upper=64)
'''

# Train a new model -- choose name cautiously to not overwrite other models
'''
model_name = "Thai_model5"
cnt = 0
graph_thrsh = 250  # The vocabulary size for embeddings
graph_clust_dic = dict()
for key in graph_clust_ratio.keys():
    if cnt < graph_thrsh-1:
        graph_clust_dic[key] = cnt
    if cnt == graph_thrsh-1:
        break
    cnt += 1

word_segmenter = WordSegmenter(input_n=50, input_t=100000, input_graph_clust_dic=graph_clust_dic,
                               input_embedding_dim=10, input_hunits=10, input_dropout_rate=0.2, input_output_dim=4,
                               input_epochs=15, input_training_data="BEST", input_evaluating_data="BEST")

# Training and saving the model
word_segmenter.train_model()
word_segmenter.test_model()
fitted_model = word_segmenter.get_model()
fitted_model.save("./Models/" + model_name)
np.save(os.getcwd() + "/Models/" + model_name + "/" + "weights", fitted_model.weights)
'''

# Choose one of the saved models to use
'''
# Thai model 1: Bi-directional LSTM (trained on BEST), grid search
# Thai model 2: Bi-directional LSTM (trained on BEST), grid search + manual reduction of hunits and embedding_size
# Thai model 3: Bi-directional LSTM (trained on BEST), grid search + extreme manual reduction of hunits and embedding_size
# Thai model 4: Bi-directional LSTM (trained on BEST), short BayesOpt choice for hunits and embedding_size
# Thai model 5: Bi-directional LSTM (trained on BEST), A very parsimonious model
# Thai temp: a temporary model, it should be used for trying new models

model_name = "Thai_model4"
input_graph_thrsh = 350  # default graph_thrsh
input_embedding_dim = 40  # default embedding_dim
input_hunits = 40  # default hunits
if model_name == "Thai_model1":
    input_graph_thrsh = 500
    input_embedding_dim = 40
    input_hunits = 40
if model_name == "Thai_model2":
    input_graph_thrsh = 350
    input_embedding_dim = 20
    input_hunits = 20
if model_name == "Thai_model3":
    input_graph_thrsh = 350
    input_embedding_dim = 15
    input_hunits = 15
if model_name == "Thai_model4":
    input_graph_thrsh = 350
    input_embedding_dim = 16
    input_hunits = 23
if model_name == "Thai_model5":
    input_graph_thrsh = 250
    input_embedding_dim = 10
    input_hunits = 10
if model_name == "Thai_temp":
    input_graph_thrsh = 350
    input_embedding_dim = 16
    input_hunits = 23

# Building the model instance and loading the trained model
cnt = 0
graph_thrsh = input_graph_thrsh  # The vocabulary size for embeddings
graph_clust_dic = dict()
for key in graph_clust_ratio.keys():
    if cnt < graph_thrsh-1:
        graph_clust_dic[key] = cnt
    if cnt == graph_thrsh-1:
        break
    cnt += 1
word_segmenter = WordSegmenter(input_n=50, input_t=100000, input_graph_clust_dic=graph_clust_dic,
                               input_embedding_dim=input_embedding_dim, input_hunits=input_hunits,
                               input_dropout_rate=0.2, input_output_dim=4, input_epochs=15,
                               input_training_data="BEST", input_evaluating_data="BEST")
model = keras.models.load_model("./Models/" + model_name)
word_segmenter.set_model(model)

# Testing the model
word_segmenter.test_model()
word_segmenter.test_model_line_by_line()
'''

################################ Burmese ################################

# Testing how ICU detects grapheme clusters and how it segments Burmese (will be deleted later on)
'''
str = "ြင်သစ်မှာ နောက်လလုပ်မယ့် သမ္မတရွေးကောက်ပွဲမှာ သူဝင်ပြိုင်မှာ မဟုတ်ဘူးလို့ ဝန်ကြီးချုပ်ဟောင်း အလိန်ယူပေက ကြေညာလိုက်ပါတယ်။"
chars_break_iterator = BreakIterator.createCharacterInstance(Locale.getUS())
word_break_iterator = BreakIterator.createWordInstance(Locale.getUS())
chars_break_iterator.setText(str)
word_break_iterator.setText(str)
char_brkpoints = [0]
for brkpoint in chars_break_iterator:
    char_brkpoints.append(brkpoint)
word_brkpoints = [0]
for brkpoint in word_break_iterator:
    word_brkpoints.append(brkpoint)
print(char_brkpoints)
print(word_brkpoints)
x = input()
'''

# Preprocess the Burmese language
# Burmese_graph_clust_ratio = preprocess_Burmese(demonstrate=False)
# np.save(os.getcwd() + '/Data/Burmese_graph_clust_ratio.npy', Burmese_graph_clust_ratio)

# Loading the graph_clust from memory
graph_clust_ratio = np.load(os.getcwd() + '/Data/Burmese_graph_clust_ratio.npy', allow_pickle=True).item()
# print_grapheme_clusters(ratios=graph_clust_ratio, thrsh=0.99)


# Dividing the my.txt data to train, validation, and test data sets.
# divide_train_test_data(input_text="./Data/my.txt", train_text="./Data/my_train.txt", valid_text="./Data/my_valid.txt",
#                        test_text="./Data/my_test.txt")
# Making a ICU segmented version of the test data, for future tests
# store_ICU_segmented_file(unseg_filename="./Data/my_test.txt", seg_filename="./Data/my_test_segmented.txt")

# Train a new model -- choose name cautiously to not overwrite other models
'''
model_name = "Burmese_temp"
cnt = 0
graph_thrsh = 350  # The vocabulary size for embeddings
graph_clust_dic = dict()
for key in graph_clust_ratio.keys():
    if cnt < graph_thrsh-1:
        graph_clust_dic[key] = cnt
    if cnt == graph_thrsh-1:
        break
    cnt += 1

word_segmenter = WordSegmenter(input_n=50, input_t=100000, input_graph_clust_dic=graph_clust_dic,
                               input_embedding_dim=20, input_hunits=20, input_dropout_rate=0.2, input_output_dim=4,
                               input_epochs=3, input_training_data="my", input_evaluating_data="my")

# Training and saving the model
word_segmenter.train_model()
word_segmenter.test_model()
fitted_model = word_segmenter.get_model()
fitted_model.save("./Models/" + model_name)
np.save(os.getcwd() + "/Models/" + model_name + "/" + "weights", fitted_model.weights)
'''

# Choose one of the saved models to use
'''
model_name = "Burmese_temp"
input_graph_thrsh = 350  # default graph_thrsh
input_embedding_dim = 40  # default embedding_dim
input_hunits = 40  # default hunits
if model_name == "Burmese_temp":
    input_graph_thrsh = 350
    input_embedding_dim = 20
    input_hunits = 20

# Building the model instance and loading the trained model
cnt = 0
graph_thrsh = input_graph_thrsh  # The vocabulary size for embeddings
graph_clust_dic = dict()
for key in graph_clust_ratio.keys():
    if cnt < graph_thrsh-1:
        graph_clust_dic[key] = cnt
    if cnt == graph_thrsh-1:
        break
    cnt += 1
word_segmenter = WordSegmenter(input_n=50, input_t=100000, input_graph_clust_dic=graph_clust_dic,
                               input_embedding_dim=input_embedding_dim, input_hunits=input_hunits,
                               input_dropout_rate=0.2, input_output_dim=4, input_epochs=3,
                               input_training_data="my", input_evaluating_data="my")
model = keras.models.load_model("./Models/" + model_name)
word_segmenter.set_model(model)

# Testing the model
word_segmenter.test_model()
word_segmenter.test_model_line_by_line()
'''



