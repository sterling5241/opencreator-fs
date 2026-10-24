#!/bin/sh
# AD5X bed load cell board (STC8G1K08A + HX711) on ttyS7, 9600 baud
# usage: loadcell.sh tare | read | diag [count]

DEV=/dev/ttyS7
OUT=/tmp/loadcell.out

send() {
	tries=0
	while [ $tries -lt 5 ]; do
		: > $OUT
		stty -F $DEV 9600 cs8 -parenb -cstopb raw -echo
		cat $DEV > $OUT & cat_pid=$!
		printf '%s\n' "$1" > $DEV
		# reply complete when longer than 12 bytes and it contains "ok" (as stock)
		i=0
		while [ $i -lt 10 ]; do
			sleep 0.1
			if [ "$(wc -c < $OUT)" -gt 12 ] && grep -q ok $OUT; then
				sleep 0.1
				kill $cat_pid 2>/dev/null
				tr -d '\r' < $OUT | tr '\n' ' '
				return 0
			fi
			i=$((i + 1))
		done
		kill $cat_pid 2>/dev/null
		tries=$((tries + 1))
	done
	return 1
}

# "command H7 ok. <raw> <grams> g" -> grams
grams() {
	echo "$1" | awk '{print $5}'
}

case "$1" in
	tare)
		n=0
		while [ $n -lt 10 ]; do
			send H1 > /dev/null || { echo "load cell: no reply to H1"; exit 1; }
			reply=$(send H7) || { echo "load cell: no reply to H7"; exit 1; }
			g=$(grams "$reply")
			if [ "${g#-}" -lt 31 ] 2>/dev/null; then
				echo "load cell: tared, $g g"
				exit 0
			fi
			n=$((n + 1))
		done
		echo "load cell: tare failed, $g g after 10 tries"
		exit 1
		;;
	read)
		reply=$(send H7) || { echo "load cell: no reply to H7"; exit 1; }
		echo "load cell: $(grams "$reply") g (raw $(echo "$reply" | awk '{print $4}'))"
		;;
	diag)
		count=${2:-10}
		min=
		max=
		n=0
		while [ $n -lt $count ]; do
			reply=$(send H7) || { echo "load cell: no reply to H7"; exit 1; }
			g=$(grams "$reply")
			[ -z "$min" ] || [ "$g" -lt "$min" ] && min=$g
			[ -z "$max" ] || [ "$g" -gt "$max" ] && max=$g
			n=$((n + 1))
		done
		echo "load cell: $count reads, min $min g, max $max g, spread $((max - min)) g"
		;;
	*)
		echo "usage: $0 tare | read | diag [count]"
		exit 1
		;;
esac
