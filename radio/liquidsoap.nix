{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.amc-peripheral;
in {
  config = lib.mkIf cfg.enable {
    services.liquidsoap.streams = {
      radio = pkgs.writeText "radio.liq" ''
      log.level := 5
      server.telnet()
      default_playlist = single("");
      settings.encoder.metadata.export := ["filename", "artist", "title", "album", "genre", "date", "tracknumber", "comment", "track", "year", "dj", "next", "apic", "metadata_url", "metadata_block_picture", "coverart"]
      queue = request.queue(id="song_requests")

      race_mode = interactive.bool("race_mode", false)
      event_mode = interactive.bool("event_mode", false)
      live = input.rtmp("rtmp://0.0.0.0:1936/live/abc123")
      announcements = request.queue(id="announcements")

      jingles = playlist(reload_mode="watch", "/var/lib/radio/jingles")
      talkshows = mksafe(
        playlist(
          reload=1,
          reload_mode="rounds",
          "/var/lib/radio/playlist/playlist.txt"
        )
      )
      def insert_intro(a, b)
        if b.metadata["intro"] != "" then
          sequence([
            a.source,
            (sequence(merge=true, [
              (once(single(b.metadata["intro"])):source),
              b.source
            ]):source)
          ])
        else
          sequence([a.source, b.source])
        end
      end

      # songs = playlist(reload_mode="watch", "/var/lib/radio/songs")
      songs = playlist("/var/lib/radio/prev_requests")
      # songs = random(weights=[1, 2], [songs, prev_requests])
      q_or_songs = fallback(track_sensitive=true, [queue, songs])
      q_or_songs = q_or_songs

      event_songs = crossfade(playlist(reload_mode="watch", "/var/lib/radio/event_songs"))

      event_jingles = playlist("/var/lib/radio/event_jingles")
      event_jingles = delay(180., event_jingles)

      race_songs = crossfade(playlist(reload_mode="watch", "/var/lib/radio/race_songs"))
      talkshows_or_jingles = rotate(weights=[1, 2], [talkshows, jingles])
      prog = rotate(weights=[1,1,3], [
        talkshows_or_jingles,
        blank(duration=2.0),
        q_or_songs,
      ])
      prog = cross(insert_intro, prog)

      radio_unnormaliszed = fallback(
        track_sensitive=false,
        [prog, default_playlist]
      )

      live = blank.strip(max_blank=2., min_noise=.1, threshold=-20., live)

      radio = nrj(normalize(radio_unnormaliszed))

      radio = switch(
        track_sensitive=false,
        [
          (race_mode, smooth_add(duration=0.5, special=live, normal=smooth_add(duration=0.5, special=announcements, normal=race_songs))),
          (event_mode, radio_unnormaliszed),
          ({true}, radio)
        ]
      )

      radio = fallback(
        track_sensitive=false,
        [radio, default_playlist]
      )

      last_metadata = ref([])
      q_or_songs.on_track(fun (m) -> last_metadata := m)
      def show_metadata(_)
        http.response(
          content_type="application/json; charset=UTF-8",
          data=metadata.json.stringify(last_metadata())
        )
      end
      harbor.http.register.simple(port=6001, "/metadata", show_metadata)

      radio = source.drop.metadata(radio)


      output.icecast(
        %mp3(bitrate=128),
        radio,
        host = "localhost",
        port = 8000,
        password = "hackme",
        mount = "/stream"
      )
      output.icecast(
        %opus,
        radio,
        host = "localhost",
        port = 8000,
        password = "hackme",
        mount = "/stream_high"
      )
    '';
      fallback = pkgs.writeText "fallback.liq" ''
        output.icecast(
          %mp3(bitrate=128),
          blank(),
          host = "localhost",
          port = 8000,
          password = "hackme",
          mount = "/fallback"
        )
      '';
    };
  };
}
