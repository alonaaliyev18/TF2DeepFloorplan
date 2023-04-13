import tensorflow as tf

def create_tfrecord(input_file, output_file):
    writer = tf.io.TFRecordWriter(output_file)
    with open(input_file, 'r') as fr:
        for line in fr:
            example = tf.train.Example(features=tf.train.Features(feature={'text':tf.train.Feature(bytes_list=tf.train.BytesList(value=[line.encode('utf-8')])),}))
            writer.write(example.SerializeToString())
    writer.close()



input_file = 'C:/Users/MixedRealityLab/PycharmProjects/TF2DeepFloorplan/dataset/r3d_test.txt'
output_file = 'dataset/r3d.tfrecords'
create_tfrecord(input_file, output_file)
