#!/usr/bin/perl
###############################################################################
# Native IPFire management page for the Blocky add-on.                       #
###############################################################################

use strict;
use warnings;

use Fcntl qw(:DEFAULT :flock O_NOFOLLOW);
use JSON::PP;

require '/var/ipfire/general-functions.pl';
require "${General::swroot}/lang.pl";
require "${General::swroot}/header.pl";

my $state_dir = "${General::swroot}/blocky";
my $pending = "$state_dir/pending/candidate.json";
my $submission_lock = "$state_dir/pending/submission.lock";
my $schema_file = '/usr/share/blocky/config.schema.json';
my $descriptor_file = '/usr/share/blocky/ui-descriptor.json';
my $max_payload = 4 * 1024 * 1024;
my %params = ( ACTION => '' );

# IPFire offers 1 MiB (normal) or 10 MiB (upload) parser limits. Select the
# latter and enforce this add-on's stricter 4 MiB bound below.
&Header::getcgihash(\%params, { wantfile => 1 });

sub json_headers {
	my ($status, $extra) = @_;
	$status ||= '200 OK';
	print "Status: $status\r\n";
	print "Content-Type: application/json; charset=utf-8\r\n";
	print "Cache-Control: no-store, max-age=0\r\n";
	print "$extra\r\n" if defined $extra && length $extra;
	print "\r\n";
}

sub json_response {
	my ($status, $value, $extra) = @_;
	json_headers($status, $extra);
	print JSON::PP->new->canonical->encode($value);
	exit 0;
}

sub read_file {
	my ($path, $limit) = @_;
	$limit ||= $max_payload;
	open(my $handle, '<', $path) or die "Cannot read $path: $!";
	local $/;
	my $content = <$handle>;
	close($handle);
	die "File exceeds size limit" if length($content) > $limit;
	return $content;
}

sub controller_output {
	my ($action) = @_;
	die "Invalid controller action" unless $action =~ /\A(?:public-data|private-data|status)\z/;
	open(my $pipe, '-|', '/usr/local/bin/blockyctrl', $action)
		or die "Cannot invoke blockyctrl: $!";
	local $/;
	my $output = <$pipe>;
	close($pipe);
	die "blockyctrl $action failed" if $? != 0;
	return $output;
}

sub run_controller {
	my ($action) = @_;
	die "Invalid controller action"
		unless $action =~ /\A(?:apply|validate|start|stop|restart|enable|disable)\z/;
	system('/usr/local/bin/blockyctrl', $action);
	return $? == 0;
}

sub write_candidate {
	my ($payload) = @_;
	die "Missing candidate payload" unless defined $payload && length $payload;
	die "Candidate exceeds 4 MiB" if length($payload) > $max_payload;
	my $decoded = JSON::PP->new->decode($payload);
	die "Candidate must be an object" unless ref($decoded) eq 'HASH';
	my $encoded = JSON::PP->new->canonical->utf8->encode($decoded);
	die "Candidate exceeds 4 MiB" if length($encoded) > $max_payload;

	my $flags = O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW;
	sysopen(my $handle, $pending, $flags, 0600) or die "Cannot write candidate: $!";
	flock($handle, LOCK_EX) or die "Cannot lock candidate: $!";
	print {$handle} $encoded;
	close($handle) or die "Cannot close candidate: $!";
}

sub current_data {
	return JSON::PP->new->decode(controller_output('public-data'));
}

my $action = $params{'ACTION'} || '';

if ($action eq 'DATA') {
	eval { json_response('200 OK', current_data()); };
	json_response('500 Internal Server Error', { ok => JSON::PP::false, error => "$@" });
}

if ($action eq 'SCHEMA') {
	eval {
		my $schema = JSON::PP->new->decode(read_file($schema_file));
		my $descriptor = JSON::PP->new->decode(read_file($descriptor_file));
		my %translations = map {
			my $key = $_;
			$key => ($Lang::tr{"blocky $key"} || $key)
		} (
			'service and status', 'full configuration', 'zones', 'routing',
			'bypass prevention', 'enforcement active', 'best effort warning',
			'save apply', 'action validate', 'action start', 'action restart',
			'action stop', 'action enable', 'action disable'
		);
		json_response('200 OK', {
			schema => $schema,
			descriptor => $descriptor,
			translations => \%translations,
		});
	};
	json_response('500 Internal Server Error', { ok => JSON::PP::false, error => "$@" });
}

if ($action eq 'APPLY') {
	eval {
		sysopen(my $lock, $submission_lock, O_WRONLY | O_CREAT | O_NOFOLLOW, 0600)
			or die "Cannot open submission lock: $!";
		flock($lock, LOCK_EX) or die "Cannot lock submission: $!";
		write_candidate($params{'PAYLOAD'});
		die "Apply failed; active settings were retained" unless run_controller('apply');
		close($lock);
		json_response('200 OK', { ok => JSON::PP::true, data => current_data() });
	};
	my $error = "$@" || 'Apply failed';
	eval {
		my $data = current_data();
		$error = $data->{'status'}->{'message'} if $data->{'status'}->{'message'};
	};
	json_response('400 Bad Request', { ok => JSON::PP::false, error => $error });
}

if ($action eq 'SERVICE') {
	my $service_action = lc($params{'SERVICE_ACTION'} || '');
	eval {
		die "Unsupported service action"
			unless $service_action =~ /\A(?:validate|start|stop|restart|enable|disable)\z/;
		die "Service action failed" unless run_controller($service_action);
		json_response('200 OK', { ok => JSON::PP::true, data => current_data() });
	};
	my $error = "$@" || 'Service action failed';
	eval {
		my $data = current_data();
		$error = $data->{'status'}->{'message'} if $data->{'status'}->{'message'};
	};
	json_response('400 Bad Request', { ok => JSON::PP::false, error => $error });
}

if ($action eq 'EXPORT') {
	my $include_secrets = ($params{'INCLUDE_SECRETS'} || '') eq 'on';
	eval {
		my $data = JSON::PP->new->decode(
			controller_output($include_secrets ? 'private-data' : 'public-data')
		);
		my $document = {
			schemaVersion => 1,
			config => $data->{'config'},
			settings => $data->{'settings'},
		};
		my $filename = $include_secrets ? 'blocky-private-export.json' : 'blocky-export.json';
		json_response(
			'200 OK',
			$document,
			"Content-Disposition: attachment; filename=\"$filename\"\r\nX-Content-Type-Options: nosniff"
		);
	};
	json_response('500 Internal Server Error', { ok => JSON::PP::false, error => "$@" });
}

&Header::showhttpheaders();
&Header::openpage($Lang::tr{'blocky service'}, 1, '');
&Header::openbigbox('100%', 'left', '', '');

&Header::openbox('100%', 'left', $Lang::tr{'blocky service'});
print <<'END_HTML';
<div id="blocky-app" data-endpoint="/cgi-bin/blocky.cgi">
	<p class="blocky-loading">Loading Blocky configuration...</p>
</div>
<noscript><p class="error">This page requires JavaScript to edit the versioned Blocky configuration schema.</p></noscript>
<script src="/include/blocky.js"></script>
END_HTML
&Header::closebox();
&Header::closebigbox();
&Header::closepage();
